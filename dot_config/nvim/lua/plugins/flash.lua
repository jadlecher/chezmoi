return {
	"folke/flash.nvim",
	opts = {
		modes = {
			char = {
				enabled = function()
					-- Snacks.nvim pickers use the "snacks_picker" filetype.
					-- If we're in a picker, disable Flash char mode so <Esc>
					-- behaves normally and closes the picker.
					local ft = vim.bo.filetype
					return ft ~= "snacks_picker"
				end,
			},
		},
	},
}
