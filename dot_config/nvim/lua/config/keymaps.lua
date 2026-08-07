local terminal = require("utils.terminal")

local mappings = {
	["<leader>aC"] = {
		modes = { "n" },
		desc = "Claude (cwd)",
		callback = function()
			terminal.open(vim.fn.getcwd(), "claude")
		end,
	},
	["<leader>ac"] = {
		modes = { "n" },
		desc = "Claude (Root Dir)",
		callback = function()
			terminal.open(LazyVim.root(), "claude")
		end,
	},
	["<leader>aX"] = {
		modes = { "n" },
		desc = "Codex (cwd)",
		callback = function()
			terminal.open(vim.fn.getcwd(), "codex")
		end,
	},
	["<leader>ax"] = {
		modes = { "n" },
		desc = "Codex (Root Dir)",
		callback = function()
			terminal.open(LazyVim.root(), "codex")
		end,
	},
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
			terminal.open(vim.fn.getcwd())
		end,
	},
	["<leader>ft"] = {
		modes = { "n" },
		desc = "Terminal (Root Dir)",
		callback = function()
			terminal.open(LazyVim.root())
		end,
	},
	["<C-/>"] = {
		modes = { "n", "t" },
		desc = "Terminal (Root Dir)",
		callback = function()
			terminal.open(LazyVim.root())
		end,
	},
	["<C-_>"] = {
		modes = { "n", "t" },
		desc = "which_key_ignore",
		callback = function()
			terminal.open(LazyVim.root())
		end,
	},
}

for key, mapping in pairs(mappings) do
	for _, mode in ipairs(mapping.modes) do
		pcall(vim.keymap.del, mode, key)
		vim.keymap.set(mode, key, mapping.callback, { desc = mapping.desc })
	end
end

vim.keymap.set("t", "<C-Space>", "<C-\\><C-n>", { desc = "Exit terminal mode" })
