local M = {}

local osc7_prefix = "\27]7;"
local visible_refresh_interval_ms = 3000
local hidden_refresh_interval_ms = 15000
local publish_heartbeat_interval_ms = 15000
local timers = {}
local timer_intervals = {}
local publish_state = {}
local state_root = vim.fn.stdpath("state")
local registry_dir = vim.fs.joinpath(state_root, "agent-workflow", "nvim")
local codex_sessions_dir = vim.fs.joinpath(vim.fn.expand("~"), ".codex", "sessions")
local codex_session_start_grace_seconds = 15
local codex_session_assignments = {}
local agent_names = { codex = true, claude = true }
local generic_agent_titles = {
	codex = true,
	["codex cli"] = true,
	claude = true,
	["claude code"] = true,
	terminal = true,
	shell = true,
	bash = true,
	zsh = true,
	fish = true,
	sh = true,
	starting = true,
	loading = true,
	ready = true,
	working = true,
	thinking = true,
	idle = true,
}
local agent_summary_max_length = 48

local function is_terminal_buffer(bufnr)
	return vim.api.nvim_buf_is_valid(bufnr) and vim.bo[bufnr].buftype == "terminal"
end

local function trim(text)
	return vim.trim(text or "")
end

local function terminal_title(bufnr)
	local title = trim(vim.b[bufnr].term_title)
	if title == "" or vim.startswith(title, "term://") then
		return nil
	end
	title = title:gsub("%s+", " ")
	if #title > 50 then
		title = title:sub(1, 49) .. "…"
	end
	return title
end

local function ensure_registry_dir()
	vim.fn.mkdir(registry_dir, "p")
end

local function run_git(args, cwd)
	local result = vim.system(vim.list_extend({ "git", "-C", cwd }, args), { text = true }):wait()
	if result.code ~= 0 then
		return nil
	end
	return trim(result.stdout)
end

local function basename(path)
	return vim.fs.basename(path)
end

local function normalize_dir(path)
	local normalized = vim.fs.normalize(path)
	if normalized ~= "/" then
		normalized = normalized:gsub("/+$", "")
	end
	return normalized
end

local function sanitize_branch(branch)
	return branch:gsub("[/\\]", "-")
end

local function write_json(path, value)
	local file = io.open(path, "w")
	if not file then
		return false
	end
	file:write(vim.json.encode(value))
	file:write("\n")
	file:close()
	return true
end

local function parse_term_uri_cwd(name)
	local cwd = name:match("^term://(.-)//")
	if not cwd or cwd == "" then
		return nil
	end
	return normalize_dir(vim.fn.fnamemodify(cwd, ":p"))
end

local function ensure_server()
	if vim.v.servername ~= "" then
		return vim.v.servername
	end

	local socket_name = string.format("agent-workflow-%d.sock", vim.fn.getpid())
	local socket_path = vim.fs.joinpath(vim.fn.stdpath("run"), socket_name)
	local ok, server = pcall(vim.fn.serverstart, socket_path)
	if ok and type(server) == "string" and server ~= "" then
		return server
	end

	return vim.v.servername
end

local function terminal_argv(bufnr)
	local channel = vim.bo[bufnr].channel
	if channel == 0 then
		return {}
	end

	local info = vim.api.nvim_get_chan_info(channel)
	return info.argv or {}
end

local function command_name(command)
	if not command or command == "" then
		return nil
	end
	return basename(command)
end

local function agent_name_from_command(name)
	if not name then
		return nil
	end

	name = name:lower()
	if name == "claude-code" then
		return "claude"
	end
	if agent_names[name] then
		return name
	end
	return nil
end

local function is_shell_command(name)
	return name == "bash" or name == "zsh" or name == "fish" or name == "sh" or name == "dash"
end

local function is_interpreter_command(name)
	return name == "node"
		or name == "nodejs"
		or name == "bun"
		or name == "deno"
		or name == "python"
		or name == "python3"
		or name == "ruby"
		or name == "perl"
		or name == "lua"
end

local function looks_like_option(token)
	return vim.startswith(token, "-")
end

local function strip_script_extension(name)
	return name:gsub("%.[cm]?js$", ""):gsub("%.ts$", ""):gsub("%.py$", ""):gsub("%.rb$", ""):gsub("%.pl$", ""):gsub("%.lua$", "")
end

local function read_proc_cmdline(pid)
	local file = io.open(string.format("/proc/%d/cmdline", pid), "rb")
	if not file then
		return {}
	end

	local raw = file:read("*a")
	file:close()
	if not raw or raw == "" then
		return {}
	end

	local argv = {}
	for token in raw:gmatch("([^%z]+)") do
		argv[#argv + 1] = token
	end
	return argv
end

local function agent_name_from_argv(argv)
	for _, token in ipairs(argv) do
		local agent = agent_name_from_command(command_name(token))
		if agent then
			return agent
		end
	end
	return nil
end

local function best_name_from_argv(argv)
	if #argv == 0 then
		return nil
	end

	local root = command_name(argv[1])
	if not root or is_shell_command(root) then
		return nil
	end

	if is_interpreter_command(root) then
		local fallback = nil
		for i = 2, #argv do
			local token = argv[i]
			if token ~= "" and not looks_like_option(token) then
				local candidate = command_name(token)
				if candidate then
					candidate = strip_script_extension(candidate)
					if candidate:find("codex", 1, true) then
						return candidate
					end
					if not fallback then
						fallback = candidate
					end
				end
			end
		end
		return fallback or root
	end

	return root
end

local function terminal_job_pid(bufnr)
	local channel = vim.bo[bufnr].channel
	if channel == 0 then
		return nil
	end

	local pid = vim.fn.jobpid(channel)
	if pid <= 0 then
		return nil
	end

	return pid
end

local function tabnr_for_buf(bufnr)
	for _, tabnr in ipairs(vim.api.nvim_list_tabpages()) do
		for _, winid in ipairs(vim.api.nvim_tabpage_list_wins(tabnr)) do
			if vim.api.nvim_win_get_buf(winid) == bufnr then
				return vim.api.nvim_tabpage_get_number(tabnr)
			end
		end
	end
	return 0
end

local function proc_cwd(bufnr)
	local pid = vim.b[bufnr].terminal_name_job_pid
	if not pid then
		pid = terminal_job_pid(bufnr)
		vim.b[bufnr].terminal_name_job_pid = pid
	end
	if not pid then
		return nil
	end

	local cwd = vim.uv.fs_realpath(string.format("/proc/%d/cwd", pid))
	if not cwd or vim.fn.isdirectory(cwd) == 0 then
		return nil
	end

	return normalize_dir(cwd)
end

local function command_from_pid(pid)
	local from_cmdline = best_name_from_argv(read_proc_cmdline(pid))
	if from_cmdline then
		return from_cmdline
	end

	local proc = vim.api.nvim_get_proc(pid)
	return proc and proc.name or nil
end

local function agent_name_from_pid(pid)
	return agent_name_from_argv(read_proc_cmdline(pid)) or agent_name_from_command(command_from_pid(pid))
end

local function pid_is_running(pid)
	return type(pid) == "number" and pid > 0 and vim.uv.fs_stat(string.format("/proc/%d", pid)) ~= nil
end

local function most_recent_direct_child_pid(pid)
	local children = vim.api.nvim_get_proc_children(pid)
	if type(children) ~= "table" or #children == 0 then
		return nil
	end

	local newest = nil
	for _, child in ipairs(children) do
		if type(child) == "number" and child > 0 and (not newest or child > newest) then
			newest = child
		end
	end
	return newest
end

local function direct_agent(bufnr)
	local job_pid = vim.b[bufnr].terminal_name_job_pid or terminal_job_pid(bufnr)
	if not job_pid then
		return nil
	end
	vim.b[bufnr].terminal_name_job_pid = job_pid

	local agent = agent_name_from_pid(job_pid) or agent_name_from_argv(terminal_argv(bufnr))
	if agent then
		return agent, job_pid
	end

	if not is_shell_command(command_from_pid(job_pid)) then
		return nil
	end
	for _, child_pid in ipairs(vim.api.nvim_get_proc_children(job_pid) or {}) do
		agent = agent_name_from_pid(child_pid)
		if agent then
			return agent, child_pid
		end
	end
	return nil
end

local function clear_agent_state(bufnr)
	local codex_session_id = vim.b[bufnr].terminal_name_codex_session_id
	if codex_session_id then
		codex_session_assignments[codex_session_id] = nil
	end
	vim.b[bufnr].terminal_name_agent_title_baseline = terminal_title(bufnr)
	vim.b[bufnr].terminal_name_agent = nil
	vim.b[bufnr].terminal_name_agent_pid = nil
	vim.b[bufnr].terminal_name_agent_started_at = nil
	vim.b[bufnr].terminal_name_agent_summary = nil
	vim.b[bufnr].terminal_name_agent_display = nil
	vim.b[bufnr].terminal_name_codex_session_id = nil
	vim.b[bufnr].terminal_name_codex_session_path = nil
	vim.b[bufnr].terminal_name_osc_title = nil
	vim.b[bufnr].terminal_name_osc_title_agent_pid = nil
end

local function tracked_agent(bufnr)
	local name = vim.b[bufnr].terminal_name_agent
	local pid = vim.b[bufnr].terminal_name_agent_pid
	if name and pid_is_running(pid) and agent_name_from_pid(pid) == name then
		return name, pid
	end
	if name or pid then
		clear_agent_state(bufnr)
	end

	name, pid = direct_agent(bufnr)
	if name then
		vim.b[bufnr].terminal_name_agent = name
		vim.b[bufnr].terminal_name_agent_pid = pid
		vim.b[bufnr].terminal_name_agent_started_at = os.time()
	end
	return name, pid
end

local function active_command(bufnr)
	local pid = vim.b[bufnr].terminal_name_job_pid
	if not pid then
		pid = terminal_job_pid(bufnr)
		vim.b[bufnr].terminal_name_job_pid = pid
	end
	if not pid then
		return nil
	end

	local child_pid = most_recent_direct_child_pid(pid)
	if child_pid then
		local child_name = command_from_pid(child_pid)
		if child_name then
			return child_name
		end
	end

	local root_name = command_from_pid(pid)
	if root_name and not is_shell_command(root_name) then
		return root_name
	end

	local argv = terminal_argv(bufnr)
	root_name = best_name_from_argv(argv)
	if root_name then
		return root_name
	end

	return nil
end

local function is_buffer_visible(bufnr)
	local wins = vim.fn.win_findbuf(bufnr)
	return type(wins) == "table" and #wins > 0
end

local function refresh_interval_for_buffer(bufnr)
	if is_buffer_visible(bufnr) then
		return visible_refresh_interval_ms
	end
	return hidden_refresh_interval_ms
end

local function tool_name(command)
	return command or ""
end

local function parse_osc7_dir(sequence)
	if type(sequence) ~= "string" or not vim.startswith(sequence, osc7_prefix) then
		return nil
	end

	local uri = sequence:gsub("^\27%]7;", "")
	uri = uri:gsub("\27\\$", "")
	uri = uri:gsub("\7$", "")

	local dir = vim.uri_to_fname(uri)
	if vim.fn.isdirectory(dir) == 0 then
		return nil
	end
	return normalize_dir(dir)
end

local function osc_title(sequence)
	if type(sequence) ~= "string" then
		return nil
	end
	local title = sequence:match("^\27%][02];(.*)")
	if not title then
		return nil
	end
	return trim(title:gsub("\27\\$", ""):gsub("\7$", ""))
end

local function title_slug(title, agent, cwd)
	title = trim(title)
	if title == "" then
		return nil
	end

	local lower = title:lower()
	lower = lower:gsub("^" .. agent .. "%s*[-:|—–]%s*", "")
	if lower == "" or generic_agent_titles[lower] then
		return nil
	end
	if lower:match("^%x%x%x%x%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%-%x%x%x%x%x%x%x%x%x%x%x%x$") then
		return nil
	end

	local dir_name = basename(cwd)
	if lower == cwd:lower() or lower == dir_name:lower() or lower:match("^/[%w%._%-%/]+$") then
		return nil
	end

	local words = {}
	for word in lower:gsub("[^%w]+", " "):gmatch("%w+") do
		local candidate = #words == 0 and word or table.concat(words, "-") .. "-" .. word
		if #candidate > agent_summary_max_length then
			break
		end
		words[#words + 1] = word
	end
	local slug = table.concat(words, "-")
	if slug == "" or generic_agent_titles[slug:gsub("-", " ")] then
		return nil
	end
	return slug
end

local function parse_timestamp(timestamp)
	if type(timestamp) ~= "string" then
		return nil
	end
	local format = "%Y-%m-%dT%H:%M:%SZ"
	local parsed = vim.fn.strptime(format, (timestamp:gsub("%.%d+Z$", "Z")))
	local utc_offset = vim.fn.strptime(format, os.date("!%Y-%m-%dT%H:%M:%SZ")) - os.time()
	return parsed - utc_offset
end

local function codex_session_metadata(path)
	local lines = vim.fn.readfile(path, "", 1)
	if #lines == 0 then
		return nil
	end

	local ok, record = pcall(vim.json.decode, lines[1])
	local payload = ok and record and record.type == "session_meta" and record.payload
	if type(payload) ~= "table" or payload.source ~= "cli" or type(payload.session_id) ~= "string" then
		return nil
	end

	local cwd = type(payload.cwd) == "string" and normalize_dir(payload.cwd) or nil
	local started_at = parse_timestamp(record.timestamp)
	if not cwd or not started_at then
		return nil
	end

	return {
		id = payload.session_id,
		cwd = cwd,
		started_at = started_at,
		path = path,
	}
end

local function codex_session_for_buffer(bufnr, cwd)
	local session_id = vim.b[bufnr].terminal_name_codex_session_id
	local session_path = vim.b[bufnr].terminal_name_codex_session_path
	if session_id and session_path and vim.fn.filereadable(session_path) == 1 then
		return session_id, session_path
	end
	if vim.fn.isdirectory(codex_sessions_dir) == 0 then
		return nil
	end

	local started_at = vim.b[bufnr].terminal_name_agent_started_at
	if not started_at then
		return nil
	end

	local candidates = {}
	for _, path in ipairs(vim.fn.globpath(codex_sessions_dir, "**/*.jsonl", false, true)) do
		local metadata = codex_session_metadata(path)
		if metadata
			and metadata.cwd == cwd
			and metadata.started_at >= started_at - codex_session_start_grace_seconds
			and not codex_session_assignments[metadata.id]
		then
			candidates[#candidates + 1] = metadata
		end
	end
	if #candidates == 0 then
		return nil
	end

	table.sort(candidates, function(left, right)
		return left.started_at > right.started_at
	end)
	local session = candidates[1]
	codex_session_assignments[session.id] = bufnr
	vim.b[bufnr].terminal_name_codex_session_id = session.id
	vim.b[bufnr].terminal_name_codex_session_path = session.path
	return session.id, session.path
end

local function codex_session_prompt(path)
	local saw_turn_context = false
	for _, line in ipairs(vim.fn.readfile(path, "", 100)) do
		local ok, record = pcall(vim.json.decode, line)
		if ok and type(record) == "table" then
			if record.type == "turn_context" then
				saw_turn_context = true
			elseif saw_turn_context
				and record.type == "response_item"
				and type(record.payload) == "table"
				and record.payload.type == "message"
				and record.payload.role == "user"
				and type(record.payload.content) == "table"
			then
				for _, content in ipairs(record.payload.content) do
					if type(content) == "table" and content.type == "input_text" and type(content.text) == "string" then
						return content.text
					end
				end
			end
		end
	end
	return nil
end

local function codex_session_summary(bufnr, cwd)
	local _, path = codex_session_for_buffer(bufnr, cwd)
	if not path then
		return nil
	end
	return title_slug(codex_session_prompt(path), "codex", cwd)
end

local function agent_summary(bufnr, agent, cwd)
	local summary = vim.b[bufnr].terminal_name_agent_summary
	if summary then
		return summary
	end
	if agent == "codex" then
		summary = codex_session_summary(bufnr, cwd)
		if summary then
			vim.b[bufnr].terminal_name_agent_summary = summary
			return summary
		end
		return nil
	end

	local titles = {}
	if vim.b[bufnr].terminal_name_osc_title_agent_pid == vim.b[bufnr].terminal_name_agent_pid then
		titles[#titles + 1] = vim.b[bufnr].terminal_name_osc_title
	end
	local fallback_title = terminal_title(bufnr)
	if fallback_title
		and fallback_title ~= vim.b[bufnr].terminal_name_agent_title_baseline
		and fallback_title ~= titles[1]
	then
		titles[#titles + 1] = fallback_title
	end
	for _, title in ipairs(titles) do
		summary = title_slug(title, agent, cwd)
		if summary then
			vim.b[bufnr].terminal_name_agent_summary = summary
			return summary
		end
	end
	return nil
end

local function build_display_label(cwd, command, title)
	if title then
		return "term:/" .. title
	end

	local dir_name = basename(cwd)
	local branch = run_git({ "rev-parse", "--abbrev-ref", "HEAD" }, cwd)

	local parts = { "term:/" }
	if command then
		parts[#parts + 1] = command .. "@"
	end
	parts[#parts + 1] = dir_name
	if branch and branch ~= "" and branch ~= "HEAD" and branch ~= "main" then
		local common_git_dir = run_git({ "rev-parse", "--path-format=absolute", "--git-common-dir" }, cwd)
		local repo_name = common_git_dir and basename(vim.fs.dirname(common_git_dir))
		if not repo_name or dir_name ~= (repo_name .. "." .. sanitize_branch(branch)) then
			parts[#parts + 1] = ":" .. branch
		end
	end

	return table.concat(parts)
end

local function build_agent_display_label(bufnr, cwd, agent)
	local summary = agent_summary(bufnr, agent, cwd)
	local detail = summary or basename(cwd)
	local label = string.format("term:/[%s] %s", agent, detail)
	vim.b[bufnr].terminal_name_agent_display = label
	return label
end

local function display_label_in_use(bufnr, label)
	for _, existing_bufnr in ipairs(vim.api.nvim_list_bufs()) do
		if existing_bufnr ~= bufnr and is_terminal_buffer(existing_bufnr) then
			local existing_label = vim.b[existing_bufnr].terminal_name_display
			if existing_label == label then
				return true
			end
		end
	end
	return false
end

local function unique_display_label(bufnr, label)
	local candidate = label
	local suffix = 2
	while display_label_in_use(bufnr, candidate) do
		candidate = string.format("%s [%d]", label, suffix)
		suffix = suffix + 1
	end
	return candidate
end

function M.capture_initial_cwd(bufnr)
	if not is_terminal_buffer(bufnr) then
		return nil
	end

	vim.b[bufnr].terminal_name_job_pid = terminal_job_pid(bufnr)
	local cwd = parse_term_uri_cwd(vim.api.nvim_buf_get_name(bufnr))
	if cwd then
		vim.b[bufnr].terminal_name_cwd = cwd
	end
	return cwd
end

function M.handle_term_request(event)
	if not is_terminal_buffer(event.buf) then
		return
	end

	local sequence = event.data and event.data.sequence
	local title = osc_title(sequence)
	if title then
		local _, agent_pid = tracked_agent(event.buf)
		vim.b[event.buf].terminal_name_osc_title = title
		vim.b[event.buf].terminal_name_osc_title_agent_pid = agent_pid
	end

	local cwd = parse_osc7_dir(sequence)
	if cwd then
		vim.b[event.buf].terminal_name_cwd = cwd
	end
	if title or cwd then
		M.refresh(event.buf)
	end
end

function M.publish(bufnr, cwd, command)
	if not is_terminal_buffer(bufnr) then
		return
	end

	ensure_registry_dir()
	local server = ensure_server()
	local tool = tool_name(command or active_command(bufnr))
	local display_name = vim.b[bufnr].terminal_name_display or ""
	local tabnr = tabnr_for_buf(bufnr)
	local job_pid = vim.b[bufnr].terminal_name_job_pid or terminal_job_pid(bufnr) or 0
	local agent = vim.b[bufnr].terminal_name_agent
	local payload = {
		server = server,
		instance_pid = vim.fn.getpid(),
		bufnr = bufnr,
		tabnr = tabnr,
		cwd = cwd or vim.b[bufnr].terminal_name_cwd or "",
		tool = tool,
		display_name = display_name,
		job_pid = job_pid,
		agent = agent or "",
		agent_pid = vim.b[bufnr].terminal_name_agent_pid or 0,
		frozen_display_name = vim.b[bufnr].terminal_name_agent_display or "",
	}
	local now_ms = vim.uv.now()
	local payload_json = vim.json.encode(payload)
	local prev = publish_state[bufnr]
	local heartbeat_due = not prev or now_ms - prev.last_ms >= publish_heartbeat_interval_ms
	if prev and prev.payload_json == payload_json and not heartbeat_due then
		return
	end

	local record = vim.deepcopy(payload)
	record.updated_at = os.date("!%Y-%m-%dT%H:%M:%SZ")
	write_json(M.registry_path(bufnr), record)
	publish_state[bufnr] = {
		payload_json = payload_json,
		last_ms = now_ms,
	}
end

local function schedule_tracking_tick(bufnr)
	local timer = timers[bufnr]
	if not timer then
		return
	end
	if not is_terminal_buffer(bufnr) then
		M.stop_tracking(bufnr)
		return
	end

	local next_interval = refresh_interval_for_buffer(bufnr)
	timer_intervals[bufnr] = next_interval
	timer:start(
		next_interval,
		0,
		vim.schedule_wrap(function()
			if not is_terminal_buffer(bufnr) then
				M.stop_tracking(bufnr)
				return
			end
			M.refresh(bufnr)
			schedule_tracking_tick(bufnr)
		end)
	)
end

function M.refresh(bufnr)
	if not is_terminal_buffer(bufnr) then
		return
	end

	local cwd = proc_cwd(bufnr) or vim.b[bufnr].terminal_name_cwd or M.capture_initial_cwd(bufnr)
	if not cwd or vim.fn.isdirectory(cwd) == 0 then
		return
	end
	vim.b[bufnr].terminal_name_cwd = cwd

	local agent = tracked_agent(bufnr)
	local command = agent or active_command(bufnr)
	local base_display = agent and build_agent_display_label(bufnr, cwd, agent)
		or build_display_label(cwd, command, terminal_title(bufnr))
	local new_display = unique_display_label(bufnr, base_display)
	local old_display = vim.b[bufnr].terminal_name_display
	vim.b[bufnr].terminal_name_display = new_display
	if old_display ~= new_display then
		pcall(vim.cmd, "redrawtabline")
		pcall(vim.cmd, "redrawstatus")
	end
	-- Keep canonical terminal buffer names (term://...) to preserve alternate-buffer jumps (^ / <C-6>).

	M.publish(bufnr, cwd, command)

	local timer = timers[bufnr]
	if timer then
		local next_interval = refresh_interval_for_buffer(bufnr)
		if timer_intervals[bufnr] ~= next_interval then
			timer:stop()
			schedule_tracking_tick(bufnr)
		end
	end
end

function M.is_terminal_buffer(bufnr)
	return is_terminal_buffer(bufnr)
end

function M.display_name(bufnr)
	if not is_terminal_buffer(bufnr) then
		return nil
	end

	local display = vim.b[bufnr].terminal_name_display
	if display and display ~= "" then
		return display
	end

	local cwd = vim.b[bufnr].terminal_name_cwd or proc_cwd(bufnr) or M.capture_initial_cwd(bufnr)
	if not cwd or vim.fn.isdirectory(cwd) == 0 then
		local raw_name = vim.api.nvim_buf_get_name(bufnr)
		return raw_name ~= "" and raw_name or nil
	end

	vim.b[bufnr].terminal_name_cwd = cwd
	local computed =
		unique_display_label(bufnr, build_display_label(cwd, active_command(bufnr), terminal_title(bufnr)))
	vim.b[bufnr].terminal_name_display = computed
	return computed
end

function M.registry_path(bufnr)
	return vim.fs.joinpath(registry_dir, string.format("%d-%d.json", vim.fn.getpid(), bufnr))
end

function M.cleanup_registry(bufnr)
	local path = M.registry_path(bufnr)
	if vim.fn.filereadable(path) == 1 then
		vim.fn.delete(path)
	end
end

function M.start_tracking(bufnr)
	if not is_terminal_buffer(bufnr) or timers[bufnr] then
		return
	end

	local timer = vim.uv.new_timer()
	timers[bufnr] = timer
	schedule_tracking_tick(bufnr)
end

function M.stop_tracking(bufnr)
	local timer = timers[bufnr]
	if not timer then
		publish_state[bufnr] = nil
		timer_intervals[bufnr] = nil
		M.cleanup_registry(bufnr)
		return
	end

	timer:stop()
	timer:close()
	timers[bufnr] = nil
	publish_state[bufnr] = nil
	timer_intervals[bufnr] = nil
	M.cleanup_registry(bufnr)
end

function M.focus_buffer(tabnr, bufnr)
	bufnr = tonumber(bufnr) or 0
	tabnr = tonumber(tabnr) or 0
	if bufnr <= 0 or not vim.api.nvim_buf_is_valid(bufnr) then
		return false
	end

	if tabnr > 0 and tabnr <= vim.fn.tabpagenr("$") then
		pcall(vim.cmd, string.format("tabnext %d", tabnr))
	end

	if vim.fn.bufwinnr(bufnr) ~= -1 then
		pcall(vim.cmd, string.format("buffer %d", bufnr))
	else
		pcall(vim.cmd, string.format("sbuffer %d", bufnr))
	end

	return true
end

local function decode_scan_snapshot()
	local scan_path = vim.fs.joinpath(state_root, "agent-workflow", "current-scan.json")
	if vim.fn.filereadable(scan_path) == 0 then
		return nil
	end

	local lines = vim.fn.readfile(scan_path)
	if #lines == 0 then
		return nil
	end

	local ok, decoded = pcall(vim.json.decode, table.concat(lines, "\n"))
	if not ok or type(decoded) ~= "table" then
		return nil
	end

	return decoded
end

function M.focus_session(session_key)
	local snapshot = decode_scan_snapshot()
	if not snapshot or type(snapshot.sessions) ~= "table" then
		return false
	end

	local server = ensure_server()
	for _, session in ipairs(snapshot.sessions) do
		if session.session_key == session_key and type(session.nvim_target) == "table" then
			local target = session.nvim_target
			if target.server == server then
				return M.focus_buffer(target.tabnr, target.bufnr)
			end
		end
	end

	return false
end

function M.focus_command(arg)
	if arg:find("^%d+:%d+$") then
		local tabnr, bufnr = arg:match("^(%d+):(%d+)$")
		return M.focus_buffer(tabnr, bufnr)
	end
	return M.focus_session(arg)
end

ensure_registry_dir()
ensure_server()

if vim.fn.exists(":AgentWorkflowFocus") == 0 then
	vim.api.nvim_create_user_command("AgentWorkflowFocus", function(opts)
		M.focus_command(opts.args)
	end, { nargs = 1 })
end

return M
