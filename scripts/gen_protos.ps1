$ErrorActionPreference = "Stop"

$protoDir = Join-Path $PSScriptRoot "..\proto"
$outDir = Join-Path $PSScriptRoot "..\backend\proto\generated"

if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

python -m grpc_tools.protoc `
  -I "$protoDir" `
  --python_out="$outDir" `
  --grpc_python_out="$outDir" `
  "$protoDir\distributed_storage.proto"
