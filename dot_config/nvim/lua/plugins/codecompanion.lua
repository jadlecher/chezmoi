local function read_file(filepath)
	local file = io.open(filepath, "r")
	if not file then
		return nil
	end
	local content = file:read("*a")
	file:close()
	return content
end

return {
	"olimorris/codecompanion.nvim",
	dependencies = {
		"nvim-lua/plenary.nvim",
		"nvim-treesitter/nvim-treesitter",
		"nvim-mini/mini.diff",
		-- extensions
		{ "ravitemer/codecompanion-history.nvim" },
	},

	opts = {
		adapters = {
			http = {
				opts = {
					show_presets = false,
					show_model_choices = true,
				},

				gemini = function()
					return require("codecompanion.adapters").extend("gemini", {})
				end,
				anthropic = function()
					return require("codecompanion.adapters").extend("anthropic", {})
				end,
				openai = function()
					local custom_models = {
						["gpt-5.2"] = {
							formatted_name = "GPT 5.2",
							opts = {
								can_reason = true,
								has_vision = true,
							},
						},
						["gpt-5.1"] = {
							formatted_name = "GPT 5.1",
							opts = {
								can_reason = true,
								has_vision = true,
							},
						},
						-- Add more models here as needed
					}

					local default_model = "gpt-5.2" -- Set your preferred default

					local base_adapter = require("codecompanion.adapters").extend("openai")
					local existing_choices = base_adapter.schema.model.choices or {}
					local updated_choices = vim.deepcopy(existing_choices)

					-- Merge custom models into existing choices
					for model_id, model_config in pairs(custom_models) do
						updated_choices[model_id] = model_config
					end

					return require("codecompanion.adapters").extend("openai", {
						schema = {
							model = {
								default = default_model,
								choices = updated_choices,
							},
						},
					})
				end,
			},

			acp = {
				opts = {
					show_presets = false,
				},

				claude_code = function()
					return require("codecompanion.adapters").extend("claude_code", {})
				end,
			},
		},

		display = {
			chat = {
				window = {
					layout = "buffer",
				},
			},
			diff = {
				provider = "mini_diff",
			},
		},

		interactions = {
			chat = {
				adapter = { name = "openai", model = "gpt-5.2" },
				-- override default binding for options (?) to preserve reverse search
				keymaps = {
					options = {
						modes = {
							n = "gH",
						},
						callback = "keymaps.options",
						description = "Options",
						hide = true,
					},
				},
				opts = {
					system_prompt = function()
						local user_prompt_file = vim.fn.getcwd() .. "/.codecompanion/system.md"
						local fallback_prompt_file = vim.fn.stdpath("config")
							.. "/lua/plugins/codecompanion/prompts/system.md"

						local prompt_content = read_file(user_prompt_file)

						if prompt_content == nil or prompt_content == "" then
							prompt_content = read_file(fallback_prompt_file)
						end

						if prompt_content == nil or prompt_content == "" then
							print(
								"CodeCompanion: No system prompt found. Looked for ./.codecompanion/system.md and default prompt."
							)
							return ""
						end

						return prompt_content
					end,
				},
			},

			inline = {
				adapter = { name = "openai", model = "gpt-4.1" },
				keymaps = {
					accept_change = {
						modes = { n = "ga" },
						description = "Accept the suggested change",
					},
					reject_change = {
						modes = { n = "gr" },
						opts = { nowait = true },
						description = "Reject the suggested change",
					},
				},
			},
		},

		extensions = {
			history = {
				enabled = true,
				opts = {
					keymap = "gh",
					auto_save = true,
					expiration_days = 0, -- 0 = disabled
					picker = "default",
					continue_last_chat = false,
					dir_to_save = vim.fn.stdpath("data") .. "/codecompanion-history",
				},
			},
		},
	},
}
