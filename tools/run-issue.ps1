[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateRange(1, 2147483647)]
    [int]$IssueNumber
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repository = "tamiro44/gmail-storage-auditor"
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BranchName = "agent/issue-$IssueNumber"

function Resolve-Application {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Candidates,
        [Parameter(Mandatory = $true)]
        [string]$InstallHint
    )

    foreach ($candidate in $Candidates) {
        $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $command) {
            return $command.Source
        }
    }
    throw "Required command not found. $InstallHint"
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$FailureMessage
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $Command @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        throw $FailureMessage
    }
}

function Invoke-ProbeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $Command @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return [pscustomobject]@{ Output = $output; ExitCode = $exitCode }
}

function Assert-CleanStatus {
    param([AllowEmptyCollection()][string[]]$StatusLines)

    if ($StatusLines.Count -ne 0) {
        throw "Working tree is not clean. Commit, stash, or remove local changes before running this command."
    }
}

function Assert-CleanWorkingTree {
    param([Parameter(Mandatory = $true)][string]$GitCommand)

    $probe = Invoke-ProbeCommand -Command $GitCommand -Arguments @("status", "--porcelain=v1", "--untracked-files=all")
    if ($probe.ExitCode -ne 0) {
        throw "Unable to inspect the Git working tree."
    }
    Assert-CleanStatus -StatusLines @($probe.Output)
}

function Assert-AgentBranchAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$GitCommand,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $localProbe = Invoke-ProbeCommand -Command $GitCommand -Arguments @("show-ref", "--verify", "--quiet", "refs/heads/$Name")
    if ($localProbe.ExitCode -eq 0) {
        throw "Local branch '$Name' already exists; refusing to overwrite it."
    }
    if ($localProbe.ExitCode -ne 1) {
        throw "Unable to check whether local branch '$Name' exists."
    }

    $remoteProbe = Invoke-ProbeCommand -Command $GitCommand -Arguments @("ls-remote", "--exit-code", "--heads", "origin", "refs/heads/$Name")
    if ($remoteProbe.ExitCode -eq 0) {
        throw "Remote branch '$Name' already exists; refusing to overwrite it."
    }
    if ($remoteProbe.ExitCode -ne 2) {
        throw "Unable to check whether remote branch '$Name' exists."
    }
}

function New-CodexTask {
    param(
        [Parameter(Mandatory = $true)][int]$Number,
        [Parameter(Mandatory = $true)][string]$Title,
        [AllowEmptyString()][string]$Body,
        [Parameter(Mandatory = $true)][string]$Url
    )

    return @"
Implement GitHub issue #$Number completely in the checked-out repository.

Title: $Title
URL: $Url

<issue_body>
$Body
</issue_body>

Operating and safety rules:
- Work only inside the current checked-out repository. Do not write elsewhere.
- Read and follow AGENTS.md, README.md, SKILL.md, docs/architecture.md, and config/policy.yaml where relevant.
- Satisfy the issue acceptance criteria with focused implementation, synthetic tests, and concise documentation.
- Preserve repository safety boundaries and conservative defaults. Do not silently weaken policy.
- Do not access Gmail, a real mailbox, Gmail credentials, OAuth tokens, exports, message bodies, addresses, IDs, or personal data.
- Do not call Gmail APIs or perform any mailbox mutation. Use synthetic fixtures only, including for mutation-path tests.
- Do not read, print, copy, export, or persist Codex/ChatGPT credentials or environment secrets.
- Do not use OPENAI_API_KEY or CODEX_API_KEY and do not add API billing or configuration.
- Do not commit, push, open or merge a pull request, tag, release, modify GitHub settings, or contact users. The surrounding local runner owns Git and GitHub publication.
- Do not modify .github/workflows or the existing GitHub Actions orchestrator unless this issue explicitly requires that exact change.
- Run relevant tests while working. Leave only the intended repository changes and do not create durable agent-session artifacts.
- If the issue conflicts with the implemented architecture or safety rules, stop and explain the conflict without expanding scope.
"@
}

function Invoke-IssueRunner {
    Set-Location -LiteralPath $RepositoryRoot

    $git = Resolve-Application -Candidates @("git.exe", "git") -InstallHint "Install Git and add it to PATH."
    Assert-CleanWorkingTree -GitCommand $git

    $gh = Resolve-Application -Candidates @("gh.exe", "gh") -InstallHint "Install GitHub CLI and add it to PATH."
    # Prefer the Windows command shim because a codex.ps1 shim can be blocked by
    # the user's PowerShell execution policy.
    $codex = Resolve-Application -Candidates @("codex.cmd", "codex.exe", "codex") -InstallHint "Install Codex CLI and add it to PATH."

    if (Test-Path Env:OPENAI_API_KEY) {
        throw "OPENAI_API_KEY is set. Remove it from this terminal so Codex uses the saved ChatGPT login."
    }
    if (Test-Path Env:CODEX_API_KEY) {
        throw "CODEX_API_KEY is set. Remove it from this terminal so Codex uses the saved ChatGPT login."
    }

    $ghAuth = Invoke-ProbeCommand -Command $gh -Arguments @("auth", "status", "--hostname", "github.com")
    if ($ghAuth.ExitCode -ne 0) {
        throw "GitHub CLI is not authenticated. Run 'gh auth login -h github.com' and retry."
    }

    $codexAuth = Invoke-ProbeCommand -Command $codex -Arguments @("login", "status")
    if ($codexAuth.ExitCode -ne 0 -or ($codexAuth.Output -join "`n") -notmatch "ChatGPT") {
        throw "Codex CLI is not authenticated with ChatGPT. Run 'codex login' and retry."
    }

    $nameProbe = Invoke-ProbeCommand -Command $git -Arguments @("config", "user.name")
    $emailProbe = Invoke-ProbeCommand -Command $git -Arguments @("config", "user.email")
    if ($nameProbe.ExitCode -ne 0 -or $emailProbe.ExitCode -ne 0 -or
        [string]::IsNullOrWhiteSpace(($nameProbe.Output -join "")) -or
        [string]::IsNullOrWhiteSpace(($emailProbe.Output -join ""))) {
        throw "Git author identity is missing. Configure git user.name and user.email, then retry."
    }

    Write-Host "Updating local main with fast-forward-only safety..."
    Invoke-CheckedCommand -Command $git -Arguments @("fetch", "origin", "main") -FailureMessage "Unable to fetch origin/main."
    Invoke-CheckedCommand -Command $git -Arguments @("switch", "main") -FailureMessage "Unable to switch to main safely."
    Invoke-CheckedCommand -Command $git -Arguments @("merge", "--ff-only", "origin/main") -FailureMessage "Local main cannot be fast-forwarded to origin/main. Resolve it manually."
    Assert-CleanWorkingTree -GitCommand $git

    $localMainProbe = Invoke-ProbeCommand -Command $git -Arguments @("rev-parse", "main")
    if ($localMainProbe.ExitCode -ne 0) { throw "Unable to resolve local main." }
    $localMain = ($localMainProbe.Output -join "").Trim()
    $remoteMainProbe = Invoke-ProbeCommand -Command $git -Arguments @("rev-parse", "origin/main")
    if ($remoteMainProbe.ExitCode -ne 0) { throw "Unable to resolve origin/main." }
    $remoteMain = ($remoteMainProbe.Output -join "").Trim()
    if ($localMain -ne $remoteMain) {
        throw "Local main differs from origin/main; refusing to build an agent branch from an unexpected commit."
    }

    Assert-AgentBranchAvailable -GitCommand $git -Name $BranchName

    $issueProbe = Invoke-ProbeCommand -Command $gh -Arguments @("issue", "view", [string]$IssueNumber, "--repo", $Repository, "--json", "number,title,body,url,state")
    if ($issueProbe.ExitCode -ne 0) {
        throw "Unable to fetch GitHub issue #$IssueNumber."
    }
    try {
        $issue = ($issueProbe.Output -join "`n") | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "GitHub CLI returned invalid issue data."
    }
    if ($issue.number -ne $IssueNumber -or $issue.state -ne "OPEN" -or
        [string]::IsNullOrWhiteSpace($issue.title) -or [string]::IsNullOrWhiteSpace($issue.url)) {
        throw "Issue #$IssueNumber is missing required fields or is not open."
    }

    Invoke-CheckedCommand -Command $git -Arguments @("switch", "-c", $BranchName) -FailureMessage "Unable to create branch '$BranchName'."
    $baseProbe = Invoke-ProbeCommand -Command $git -Arguments @("rev-parse", "HEAD")
    if ($baseProbe.ExitCode -ne 0) { throw "Unable to record the branch base commit." }
    $baseCommit = ($baseProbe.Output -join "").Trim()

    $issueBody = if ($null -eq $issue.body) { "" } else { [string]$issue.body }
    $task = New-CodexTask -Number $IssueNumber -Title $issue.title -Body $issueBody -Url $issue.url
    Write-Host "Running local Codex for issue #$IssueNumber on $BranchName..."
    $task | & $codex exec --ephemeral --ignore-user-config --sandbox workspace-write --approve-for-me -c sandbox_workspace_write.network_access=false -C $RepositoryRoot -
    if ($LASTEXITCODE -ne 0) {
        throw "Codex did not complete successfully. Local changes, if any, remain on '$BranchName' for inspection."
    }

    $currentProbe = Invoke-ProbeCommand -Command $git -Arguments @("rev-parse", "HEAD")
    $currentCommit = ($currentProbe.Output -join "").Trim()
    if ($currentProbe.ExitCode -ne 0 -or $currentCommit -ne $baseCommit) {
        throw "Codex changed Git history even though the task forbade commits. Inspect '$BranchName' manually."
    }

    $pythonCandidates = @(
        (Join-Path $RepositoryRoot ".venv\Scripts\python.exe"),
        "python.exe",
        "python"
    )
    $python = Resolve-Application -Candidates $pythonCandidates -InstallHint "Install Python 3.11 or newer."

    Write-Host "Running the full repository test suite..."
    Invoke-CheckedCommand -Command $python -Arguments @("-B", "-m", "unittest", "discover", "-s", "tests", "-v") -FailureMessage "Repository tests failed; nothing was pushed."
    Invoke-CheckedCommand -Command $git -Arguments @("diff", "--check") -FailureMessage "git diff --check failed; nothing was pushed."

    $changesProbe = Invoke-ProbeCommand -Command $git -Arguments @("status", "--porcelain=v1", "--untracked-files=all")
    if ($changesProbe.ExitCode -ne 0) { throw "Unable to inspect Codex changes." }
    $changes = @($changesProbe.Output)
    if ($changes.Count -eq 0) {
        throw "Codex completed without repository changes; nothing was pushed."
    }

    Write-Host "Change summary:"
    & $git status --short
    if ($LASTEXITCODE -ne 0) { throw "Unable to show repository status." }
    & $git diff --stat
    if ($LASTEXITCODE -ne 0) { throw "Unable to show diff summary." }

    Invoke-CheckedCommand -Command $git -Arguments @("add", "-A") -FailureMessage "Unable to stage changes."
    Invoke-CheckedCommand -Command $git -Arguments @("diff", "--cached", "--check") -FailureMessage "Staged whitespace validation failed; nothing was pushed."
    Invoke-CheckedCommand -Command $git -Arguments @("commit", "-m", "Implement issue #$IssueNumber") -FailureMessage "Unable to commit the validated implementation."
    Invoke-CheckedCommand -Command $git -Arguments @("push", "--set-upstream", "origin", $BranchName) -FailureMessage "Unable to push '$BranchName'."

    $pullRequestBody = @"
Closes #$IssueNumber

Implemented locally with Codex from the issue title and acceptance criteria.

Validation performed by the local runner:
- Full repository test suite
- git diff --check

Human review and merge are required. This workflow never merges automatically.
"@
    & $gh pr create --repo $Repository --base main --head $BranchName --title "Implement #$IssueNumber`: $($issue.title)" --body $pullRequestBody
    if ($LASTEXITCODE -ne 0) {
        throw "Branch '$BranchName' was pushed, but the pull request could not be opened. Create it manually; do not rerun over the existing branch."
    }

    Write-Host "Done. Review the pull request before merging."
}

if ($MyInvocation.InvocationName -ne ".") {
    try {
        Invoke-IssueRunner
    } catch {
        Write-Error $_.Exception.Message
        exit 1
    }
}
