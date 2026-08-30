#!/usr/bin/env pwsh
# Thin wrapper so you can type `.\lib.ps1 add <url>` from anywhere in the repo.
& py "$PSScriptRoot\lib.py" @args
exit $LASTEXITCODE
