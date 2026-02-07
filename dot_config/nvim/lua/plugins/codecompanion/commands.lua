local M = {}

-- Add visually selected code to the current chat buffer
-- without additional prefixes like "Here is some code from...".
-- Based on the original "CodeCompanionChat Add" command from the plugin
---@param args table
---@return nil
function M.add_selection_to_chat(args)
	local CodeCompanion = require("codecompanion")
	local config = require("codecompanion.config")
	local log = require("codecompanion.utils.log")
	local context_utils = require("codecompanion.utils.context")

	if not config.can_send_code() then
		log:warn("Sending of code has been disabled")
		return
	end

	local context = context_utils.get(vim.api.nvim_get_current_buf(), args)
	local content = table.concat(context.lines, "\n")

	local chat = CodeCompanion.last_chat()

	if not chat then
		chat = CodeCompanion.chat()

		if not chat then
			log:warn("Could not create chat buffer")
			return
		end
	end

	chat:add_buf_message({
		role = config.constants.USER_ROLE,
		content = "```" .. context.filetype .. "\n" .. content .. "\n```\n",
	})
	chat.ui:open()
end

--- Add visually selected code to a NEW chat buffer
---@param args table
---@return nil
function M.add_selection_to_new_chat(args)
	local CodeCompanion = require("codecompanion")
	local config = require("codecompanion.config")
	local log = require("codecompanion.utils.log")
	local context_utils = require("codecompanion.utils.context")

	if not config.can_send_code() then
		log:warn("Sending of code has been disabled")
		return
	end

	local context = context_utils.get(vim.api.nvim_get_current_buf(), args)
	local content = table.concat(context.lines, "\n")

	-- Always create a *new* chat buffer
	local chat = CodeCompanion.chat()

	if not chat then
		log:warn("Could not create chat buffer")
		return
	end

	chat:add_buf_message({
		role = config.constants.USER_ROLE,
		content = "```" .. context.filetype .. "\n" .. content .. "\n```\n",
	})
	chat.ui:open()
end

return M
