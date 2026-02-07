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

-- disable line numbers in new terminal buffers
vim.api.nvim_create_autocmd("TermOpen", {
	command = "setlocal nonumber | setlocal norelativenumber",
})
