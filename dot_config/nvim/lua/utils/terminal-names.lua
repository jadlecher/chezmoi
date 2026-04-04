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

local function build_label(cwd)
	local dir_name = basename(cwd)
	local branch = run_git({ "rev-parse", "--abbrev-ref", "HEAD" }, cwd)
	if not branch or branch == "" or branch == "HEAD" then
		return dir_name
	end

	local common_git_dir = run_git({ "rev-parse", "--path-format=absolute", "--git-common-dir" }, cwd)
	local repo_name = common_git_dir and basename(vim.fs.dirname(common_git_dir))
	if repo_name and dir_name == (repo_name .. "." .. sanitize_branch(branch)) then
		return dir_name
	end

	return string.format("term:/%s:%s", dir_name, branch)
end

local function unique_buffer_name(bufnr, label)
	local base_name = label
	if not vim.startswith(label, "term:/") then
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

	local target_name = unique_buffer_name(bufnr, build_label(cwd))
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
