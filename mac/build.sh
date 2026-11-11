#!/bin/bash
# 构建 LiveBrain Console.app（需 Xcode Command Line Tools 的 swiftc）
set -euo pipefail
cd "$(dirname "$0")"

APP="LiveBrain Console.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -o "$APP/Contents/MacOS/LiveBrainConsole" main.swift \
    -framework Cocoa -framework WebKit

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>LiveBrain Console</string>
    <key>CFBundleDisplayName</key>       <string>播控大脑控制台</string>
    <key>CFBundleIdentifier</key>        <string>com.livebrain.console</string>
    <key>CFBundleExecutable</key>        <string>LiveBrainConsole</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>    <string>12.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key><true/>
    </dict>
</dict>
</plist>
PLIST

# 临时签名（本机可打开；分发需开发者证书）
codesign --force --sign - "$APP" 2>/dev/null || true
echo "构建完成：$APP"
