return {
	"folke/which-key.nvim",
	opts = function(_, opts)
		local groups = { {
			"<leader>a",
			group = "ai",
			mode = { "n", "v" },
		} }
		opts.spec = opts.spec or {}
		for _, group in ipairs(groups) do
			table.insert(opts.spec, group)
		end
		return opts
	end,
}
