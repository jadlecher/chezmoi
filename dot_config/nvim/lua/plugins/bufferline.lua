return {
	{
		"akinsho/bufferline.nvim",
		opts = {
			options = {
				mode = "tabs",
				show_buffer_close_icons = false,
				show_close_icon = false,
				name_formatter = function(tab)
					local bufnr = tab.bufnr or tab.buf
					if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
						return vim.b[bufnr].terminal_name_display or tab.name
					end
					return tab.name
				end,
			},
		},
	},
}
