local M = {}

local osc7_prefix = "\27]7;"
local refresh_interval_ms = 1000
local timers = {}

local function is_terminal_buffer(bufnr)
	return vim.api.nvim_buf_is_valid(bufnr) and vim.bo[bufnr].buftype == "terminal"
end

local function trim(text)
	return vim.trim(text or "")
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

local function parse_term_uri_cwd(name)
	local cwd = name:match("^term://(.-)//")
	if not cwd or cwd == "" then
		return nil
	end
	return normalize_dir(vim.fn.fnamemodify(cwd, ":p"))
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

local function deepest_child_name(pid)
	local children = vim.api.nvim_get_proc_children(pid)
	if #children == 0 then
		return nil
	end

	for i = #children, 1, -1 do
		local child_pid = children[i]
		local descendant = deepest_child_name(child_pid)
		if descendant then
			return descendant
		end
		local child_name = command_from_pid(child_pid)
		if child_name and not is_shell_command(child_name) then
			return child_name
		end
	end

	return nil
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

	local child_name = deepest_child_name(pid)
	if child_name then
		return child_name
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

local function build_display_label(cwd, command)
	local dir_name = basename(cwd)
	local branch = run_git({ "rev-parse", "--abbrev-ref", "HEAD" }, cwd)
	local prefix = command and (command .. "@") or ""
	if not branch or branch == "" or branch == "HEAD" or branch == "main" then
		return prefix ~= "" and ("terminal:" .. prefix .. dir_name) or dir_name
	end

	local common_git_dir = run_git({ "rev-parse", "--path-format=absolute", "--git-common-dir" }, cwd)
	local repo_name = common_git_dir and basename(vim.fs.dirname(common_git_dir))
	if repo_name and dir_name == (repo_name .. "." .. sanitize_branch(branch)) then
		return prefix ~= "" and ("terminal:" .. prefix .. dir_name) or dir_name
	end

	return string.format("term:%s%s:%s", prefix, dir_name, branch)
end

local function build_safe_label(cwd, command)
	local dir_name = basename(cwd)
	local branch = run_git({ "rev-parse", "--abbrev-ref", "HEAD" }, cwd)
	local prefix = command and (command .. "@") or ""
	if not branch or branch == "" or branch == "HEAD" or branch == "main" then
		return prefix ~= "" and ("term:" .. prefix .. dir_name) or dir_name
	end

	local common_git_dir = run_git({ "rev-parse", "--path-format=absolute", "--git-common-dir" }, cwd)
	local repo_name = common_git_dir and basename(vim.fs.dirname(common_git_dir))
	if repo_name and dir_name == (repo_name .. "." .. sanitize_branch(branch)) then
		return prefix ~= "" and ("term:" .. prefix .. dir_name) or dir_name
	end

	return string.format("term:%s%s:%s", prefix, dir_name, branch)
end

local function unique_buffer_name(bufnr, label)
	local base_name = label
	if not vim.startswith(label, "term:") then
		base_name = "terminal://" .. label
	end
	local current_name = vim.api.nvim_buf_get_name(bufnr)
	if current_name == base_name then
		return current_name
	end

	local candidate = base_name
	local suffix = 2
	while true do
		local existing = vim.fn.bufnr(candidate)
		if existing == -1 or existing == bufnr then
			return candidate
		end
		candidate = string.format("%s [%d]", base_name, suffix)
		suffix = suffix + 1
	end
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

	local cwd = parse_osc7_dir(event.data and event.data.sequence)
	if not cwd then
		return
	end

	vim.b[event.buf].terminal_name_cwd = cwd
	M.refresh(event.buf)
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

	local command = active_command(bufnr)
	local old_display = vim.b[bufnr].terminal_name_display
	local new_display = build_display_label(cwd, command)
	vim.b[bufnr].terminal_name_display = new_display
	if old_display ~= new_display then
		pcall(vim.cmd, "redrawtabline")
	end

	local target_name = unique_buffer_name(bufnr, build_safe_label(cwd, command))
	if vim.api.nvim_buf_get_name(bufnr) == target_name then
		return
	end

	pcall(vim.api.nvim_buf_set_name, bufnr, target_name)
end

function M.start_tracking(bufnr)
	if not is_terminal_buffer(bufnr) or timers[bufnr] then
		return
	end

	local timer = vim.uv.new_timer()
	timers[bufnr] = timer
	timer:start(
		refresh_interval_ms,
		refresh_interval_ms,
		vim.schedule_wrap(function()
			if not is_terminal_buffer(bufnr) then
				M.stop_tracking(bufnr)
				return
			end
			M.refresh(bufnr)
		end)
	)
end

function M.stop_tracking(bufnr)
	local timer = timers[bufnr]
	if not timer then
		return
	end

	timer:stop()
	timer:close()
	timers[bufnr] = nil
end

return M
