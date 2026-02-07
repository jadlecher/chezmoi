vim.api.nvim_create_autocmd({ "BufEnter", "BufWinEnter" }, {
	pattern = { "*/hypr/**.conf" },
	callback = function()
		vim.bo.filetype = "hyprlang"
	end,
})
