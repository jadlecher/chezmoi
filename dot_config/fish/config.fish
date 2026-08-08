if status is-interactive
    set -g fish_greeting

    function prompt_login
    end

    alias vi nvim
    alias vim nvim
    alias k kubectl

    function vic
        find . -type f \
            -not \( -path "*/build/*" -o -path "*/.cache/*" -o -path "*/.git/*" \) \
            -not -name ".*" \
            -exec nvim {} +
    end

    set -gx VISUAL /usr/bin/nvim
    set -gx EDITOR /usr/bin/nvim
    if test -f /etc/ssl/certs/ca-certificates.crt
        set -gx REQUESTS_CA_BUNDLE /etc/ssl/certs/ca-certificates.crt
    end

    fish_add_path ~/.local/bin ~/.cargo/bin ~/.npm-global/bin
    if test -d ~/.opencode/bin
        fish_add_path ~/.opencode/bin
    end

    if test -f ~/.config/shell/secrets.local
        source ~/.config/shell/secrets.local
    end

    if type -q kubectl
        kubectl completion fish 2>/dev/null | source
        complete -c k -w kubectl
    end

    if type -q coder
        coder completion --shell fish --print 2>/dev/null | source
    end

    if type -q wt
        wt config shell init fish | source
    end

    # Enable zoxide directory jumping when zoxide is installed.
    if type -q zoxide
        zoxide init fish | source
    end
end
