local M = {}

function M.open(cwd, command)
	local bufnr = vim.api.nvim_create_buf(true, false)
	vim.api.nvim_win_set_buf(0, bufnr)

	local job = vim.fn.jobstart({ command or vim.env.SHELL }, { cwd = cwd, term = true })
	if job <= 0 then
		vim.api.nvim_buf_delete(bufnr, { force = true })
		error("failed to start " .. (command or "$SHELL"))
	end

	vim.cmd.startinsert()
end

return M
