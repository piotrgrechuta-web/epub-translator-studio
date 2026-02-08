param(
    [string]$Owner = "Piotr-Grechuta",
    [string]$Repo = "epub-translator-studio",
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $SourceDir) {
    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
    $SourceDir = Join-Path $repoRoot "docs\wiki"
}

if (-not (Test-Path $SourceDir)) {
    throw "Wiki source directory not found: $SourceDir"
}

$wikiUrl = "https://github.com/$Owner/$Repo.wiki.git"
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("ets-wiki-" + [Guid]::NewGuid().ToString("N"))

try {
    git clone $wikiUrl $tmp | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot clone $wikiUrl. Initialize wiki backend first: https://github.com/$Owner/$Repo/wiki"
    }

    Copy-Item (Join-Path $SourceDir "*.md") $tmp -Force

    Push-Location $tmp
    try {
        git add .
        $changes = git status --porcelain
        if (-not $changes) {
            Write-Output "No wiki changes to publish."
            exit 0
        }

        git config user.name "Piotr-Grechuta"
        git config user.email "Piotr-Grechuta@users.noreply.github.com"
        git commit -m "Update wiki from docs/wiki"
        git push origin HEAD | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Wiki push failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Output "Wiki published: https://github.com/$Owner/$Repo/wiki"
}
catch {
    Write-Error $_
    exit 1
}
finally {
    if (Test-Path $tmp) {
        Remove-Item -Recurse -Force $tmp
    }
}
