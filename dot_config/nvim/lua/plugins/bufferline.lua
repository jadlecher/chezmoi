return {
	{
		"akinsho/bufferline.nvim",
		opts = {
			options = {
				mode = "tabs",
				show_buffer_close_icons = false,
				show_close_icon = false,
				name_formatter = function(tab)
					local function strip_duplicate_suffix(name)
						return (name or ""):gsub(" %[%d+%]$", "")
					end

					local bufnr = tab.bufnr or tab.buf
					if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
						local display_name = vim.b[bufnr].terminal_name_display
						if display_name and display_name ~= "" then
							return strip_duplicate_suffix(display_name)
						end

						local bufname = vim.api.nvim_buf_get_name(bufnr)
						if vim.startswith(bufname, "term:/") then
							return strip_duplicate_suffix(bufname)
						end
					end

					if vim.startswith(tab.name, "term:/") then
						return strip_duplicate_suffix(tab.name)
					end

					return tab.name
				end,
			},
		},
	},
}
