return {
	"nvim-lualine/lualine.nvim",
	opts = function(_, opts)
		-- Enable codecompanion integration
		table.insert(opts.sections.lualine_x, { require("plugins.codecompanion.lualine") })
	end,
}
