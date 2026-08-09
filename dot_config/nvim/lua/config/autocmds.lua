local terminal_names = require("utils.terminal-names")

local function augroup(name)
	return vim.api.nvim_create_augroup("config_" .. name, { clear = true })
end

vim.api.nvim_create_user_command("Scratch", function()
	vim.cmd("enew")
	vim.opt_local.buftype = "nofile"
	vim.opt_local.bufhidden = "hide"
	vim.opt_local.modified = false
	vim.opt_local.swapfile = false
end, {})

---@param ctx table<string, any>
vim.api.nvim_create_user_command("Redir", function(ctx)
	local command = vim.api.nvim_parse_cmd(ctx.args, {})
	local lines = vim.split(vim.api.nvim_cmd(command, { output = true }), "\n", { plain = true })
	vim.cmd("Scratch")
	vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
end, { nargs = "+", complete = "command" })

vim.api.nvim_create_autocmd("BufDelete", {
	group = augroup("dashboard_after_last_buffer"),
	callback = function(args)
		if vim.bo[args.buf].filetype == "snacks_dashboard" then
			return
		end

		vim.schedule(function()
			local buffers = vim.fn.getbufinfo({ buflisted = 1 })
			if #buffers ~= 1 then
				return
			end

			local buf = buffers[1].bufnr
			if not vim.api.nvim_buf_is_valid(buf)
				or vim.api.nvim_buf_get_name(buf) ~= ""
				or vim.bo[buf].buftype ~= ""
				or vim.bo[buf].filetype ~= ""
				or vim.bo[buf].modified
				or vim.api.nvim_buf_line_count(buf) ~= 1
				or vim.api.nvim_buf_get_lines(buf, 0, 1, false)[1] ~= ""
			then
				return
			end

			local win = vim.fn.bufwinid(buf)
			local snacks = _G.Snacks
			if win ~= -1 and snacks and snacks.dashboard then
				snacks.dashboard({ buf = buf, win = win })
			end
		end)
	end,
})

-- disable line numbers in new terminal buffers
vim.api.nvim_create_autocmd("TermOpen", {
	group = augroup("terminal_open"),
	callback = function(args)
		vim.opt_local.number = false
		vim.opt_local.relativenumber = false
		terminal_names.capture_initial_cwd(args.buf)
		terminal_names.refresh(args.buf)
		terminal_names.start_tracking(args.buf)
	end,
})

vim.api.nvim_create_autocmd("TermRequest", {
	group = augroup("terminal_name_requests"),
	callback = terminal_names.handle_term_request,
})

vim.api.nvim_create_autocmd("BufEnter", {
	group = augroup("terminal_name_refresh"),
	callback = function(args)
		terminal_names.refresh(args.buf)
	end,
})

vim.api.nvim_create_autocmd({ "TermClose", "BufWipeout" }, {
	group = augroup("terminal_name_cleanup"),
	callback = function(args)
		terminal_names.stop_tracking(args.buf)
	end,
})
