local M = {}

function M.find(root)
  if root == nil then root = vim.fn.getcwd() end -- default to cwd
  directory = vim.fn.fnamemodify(root, ":t")     -- assume the executable will be named the same as the directory
  return vim.fn.findfile(directory, 'build/**')
end

return M
