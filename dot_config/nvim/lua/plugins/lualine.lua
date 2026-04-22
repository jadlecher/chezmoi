local terminal_names = require("utils.terminal-names")

return {
	"nvim-lualine/lualine.nvim",
	opts = function(_, opts)
		local lualine_c = opts.sections and opts.sections.lualine_c
		if type(lualine_c) == "table" then
			for i, component in ipairs(lualine_c) do
				if type(component) == "table" and type(component[1]) == "function" and component.cond == nil then
					local original = component[1]
					lualine_c[i] = {
						function(self)
							local label = terminal_names.display_name(vim.api.nvim_get_current_buf())
							if label and label ~= "" then
								return label
							end
							return original(self)
						end,
					}
					break
				end
			end
		end

		-- Enable codecompanion integration
		table.insert(opts.sections.lualine_x, { require("plugins.codecompanion.lualine") })
	end,
}
