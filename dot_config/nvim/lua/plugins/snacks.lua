local terminal_names = require("utils.terminal-names")

return {
	"folke/snacks.nvim",
	opts = function(_, opts)
		opts = opts or {}
		opts.scroll = vim.tbl_deep_extend("force", opts.scroll or {}, { enabled = false })

		opts.picker = opts.picker or {}
		opts.picker.sources = opts.picker.sources or {}
		local buffers = opts.picker.sources.buffers or {}
		local previous_transform = buffers.transform

		local previous_transform_fn = nil
		if type(previous_transform) == "function" then
			previous_transform_fn = previous_transform
		elseif type(previous_transform) == "string" then
			previous_transform_fn = require("snacks.picker.transform")[previous_transform]
		end

		buffers.transform = function(item, ctx)
			if previous_transform_fn then
				local transformed = previous_transform_fn(item, ctx)
				if transformed == false then
					return false
				end
				if type(transformed) == "table" then
					item = transformed
				end
			end

			local bufnr = item.buf or item.bufnr
			if type(bufnr) ~= "number" or bufnr <= 0 or not terminal_names.is_terminal_buffer(bufnr) then
				return item
			end

			local label = terminal_names.display_name(bufnr)
			if not label or label == "" then
				return item
			end

			item.name = label
			item.file = label
			item._path = nil
			item.text = table.concat({
				tostring(item.buf or ""),
				item.name or "",
				item.filetype or "",
				item.buftype or "",
			}, " ")
			return item
		end

		opts.picker.sources.buffers = buffers
	end,
}
