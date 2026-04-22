local terminal_names = require("utils.terminal-names")

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

					local function tab_bufnr()
						local bufnr = tab.bufnr or tab.buf
						if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
							return bufnr
						end

						local tabnr = tonumber(tab.tabnr or tab.id)
						if tabnr and tabnr > 0 and vim.api.nvim_tabpage_is_valid(tabnr) then
							local winid = vim.api.nvim_tabpage_get_win(tabnr)
							if winid and vim.api.nvim_win_is_valid(winid) then
								return vim.api.nvim_win_get_buf(winid)
							end
						end

						return nil
					end

					local bufnr = tab_bufnr()
					if bufnr and vim.api.nvim_buf_is_valid(bufnr) then
						local display_name = terminal_names.display_name(bufnr)
						if display_name and display_name ~= "" then
							return strip_duplicate_suffix(display_name)
						end

						local bufname = vim.api.nvim_buf_get_name(bufnr)
						if vim.startswith(bufname, "term:/") or vim.startswith(bufname, "term://") then
							return strip_duplicate_suffix(bufname)
						end
					end

					if vim.startswith(tab.name, "term:/") or vim.startswith(tab.name, "term://") then
						return strip_duplicate_suffix(tab.name)
					end

					return tab.name
				end,
			},
		},
	},
}
