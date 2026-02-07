local map = vim.keymap.set

-- CodeCompanion keymaps
map("n", "<leader>aa", "<cmd>CodeCompanionActions<cr>", { desc = "CodeCompanion Actions" })
map("n", "<leader>an", "<cmd>CodeCompanionChat<cr>", { desc = "CodeCompanion New Chat" })
map("n", "<leader>ac", "<cmd>CodeCompanionChat Toggle<cr>", { desc = "CodeCompanion Toggle Chat" })
map("n", "<leader>ah", "<cmd>CodeCompanionHistory<cr>", { desc = "CodeCompanion History" })
map(
	"v",
	"<leader>aa",
	require("plugins.codecompanion.commands").add_selection_to_chat,
	{ desc = "CodeCompanion Chat: Add Selection" }
)
map(
	"v",
	"<leader>ao",
	require("plugins.codecompanion.commands").add_selection_to_chat,
	{ desc = "CodeCompanion Chat: Add Selection" }
)
map("v", "<leader>ac", ":CodeCompanion<space>", { desc = "CodeCompanion Inline Assistant" })
