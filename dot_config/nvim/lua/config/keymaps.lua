local function open_terminal(cwd)
	local bufnr = vim.api.nvim_create_buf(true, false)
	vim.api.nvim_win_set_buf(0, bufnr)

	local job = vim.fn.jobstart({ vim.env.SHELL }, { cwd = cwd, term = true })
	if job <= 0 then
		vim.api.nvim_buf_delete(bufnr, { force = true })
		error("failed to start $SHELL")
	end

	vim.cmd.startinsert()
end

local mappings = {
	["<leader>fT"] = function()
		open_terminal(vim.fn.getcwd())
	end,
	["<leader>ft"] = function()
		open_terminal(LazyVim.root())
	end,
	["<C-/>"] = function()
		open_terminal(LazyVim.root())
	end,
	["<C-_>"] = function()
		open_terminal(LazyVim.root())
	end,
}

for key, callback in pairs(mappings) do
	for _, mode in ipairs({ "n", "t" }) do
		pcall(vim.keymap.del, mode, key)
		vim.keymap.set(mode, key, callback, { desc = "Terminal (New Buffer)" })
	end
end
