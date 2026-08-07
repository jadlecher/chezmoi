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
	["<leader>bD"] = {
		modes = { "n" },
		desc = "Delete Buffer and Window",
		callback = function()
			vim.cmd(vim.bo.buftype == "terminal" and "bdelete!" or "bdelete")
		end,
	},
	["<leader>fT"] = {
		modes = { "n" },
		desc = "Terminal (cwd)",
		callback = function()
			open_terminal(vim.fn.getcwd())
		end,
	},
	["<leader>ft"] = {
		modes = { "n" },
		desc = "Terminal (Root Dir)",
		callback = function()
			open_terminal(LazyVim.root())
		end,
	},
	["<C-/>"] = {
		modes = { "n", "t" },
		desc = "Terminal (Root Dir)",
		callback = function()
			open_terminal(LazyVim.root())
		end,
	},
	["<C-_>"] = {
		modes = { "n", "t" },
		desc = "which_key_ignore",
		callback = function()
			open_terminal(LazyVim.root())
		end,
	},
}

for key, mapping in pairs(mappings) do
	for _, mode in ipairs(mapping.modes) do
		pcall(vim.keymap.del, mode, key)
		vim.keymap.set(mode, key, mapping.callback, { desc = mapping.desc })
	end
end

vim.keymap.set("t", "<C-Space><Space>", "<C-\\><C-n>", { desc = "Exit terminal mode" })
vim.keymap.set("t", "<C-Space>h", "<C-\\><C-n><C-w>h", { desc = "Jump left" })
vim.keymap.set("t", "<C-Space>j", "<C-\\><C-n><C-w>j", { desc = "Jump down" })
vim.keymap.set("t", "<C-Space>k", "<C-\\><C-n><C-w>k", { desc = "Jump up" })
vim.keymap.set("t", "<C-Space>l", "<C-\\><C-n><C-w>l", { desc = "Jump right" })
