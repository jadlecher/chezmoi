if status is-interactive
    function prompt_login
    end

    # Enable zoxide directory jumping when zoxide is installed.
    if type -q zoxide
        zoxide init fish | source
    end
end
