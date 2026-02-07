local M = {}

local themes = { light = "light", dark = "dark" }

local function read_gsettings()
	local command = "gsettings get org.gnome.desktop.interface color-scheme"
	local output = vim.fn.system(command)
	if vim.v.shell_error ~= 0 then
		error('an error occurred when exectuing the command "' .. command .. '": ' .. output)
	end
	local theme = string.match(output, "'prefer%-(%a+)'")
	theme = themes[theme] -- attempt to coerce to valid value
	if theme == nil then
		error('invalid gsettings color-scheme "' .. output .. '"')
	end
	return theme
end

local function read_xsettings()
	-- determine if 'Net/ThemeName' in xsettingsd.conf matches expected light or dark backgrounds
	local xsettings_file = os.getenv("HOME") .. "/.config/xsettingsd/xsettingsd.conf"
	if vim.fn.filereadable(xsettings_file) > 0 then
		local xsettings = vim.fn.readfile(xsettings_file)
		local background = nil
		for _, value in pairs(xsettings) do
			background = string.match(value, 'Net/ThemeName%s+"([%a%-]+)"'):lower()
			break
		end
		if background == nil then
			return nil
		end
		for key, value in pairs(require("catppuccin").options.background) do
			if background:find(value) and themes[key] ~= nil then
				return key
			end
		end
	end
	return nil
end

local function get_gtk_theme()
	local theme = nil
	if vim.fn.executable("gsettings") == 1 then
		theme = read_gsettings()
	else
		theme = read_xsettings()
	end
	return theme
end

function M.switch()
	local background = get_gtk_theme()
	if background ~= nil then
		vim.opt.background = background
	end
end

return M
