# MCP接続

## WindowsのCodex CLI

アプリを展開したフォルダーで、PowerShellから登録します。

```powershell
codex mcp add mcpaint -- "C:\Tools\MCPaint\MCPaint-MCP.exe"
codex mcp list
```

または `.codex/config.toml` に追加します。既存の設定は消さず、この項目を追記してください。

```toml
[mcp_servers.mcpaint]
command = 'C:\Tools\MCPaint\MCPaint-MCP.exe'
tool_timeout_sec = 150
```

Codexの新しいセッションから使います。`MCPaint.exe`がすでに起動していれば同じ画面を操作します。起動していない場合は最初の操作で起動します。

## WSLのCodex CLI

Windowsアプリを操作する場合は、WindowsのMCP EXEをWSLから起動します。Python版のMCPをWSL側で起動すると、Windowsとは別のホーム・GUIを参照するため使わないでください。

```toml
[mcp_servers.mcpaint]
command = '/mnt/c/Tools/MCPaint/MCPaint-MCP.exe'
tool_timeout_sec = 150
```

WSLのWindows実行ファイル起動機能が有効な環境が対象です。この経路の実機検証は利用者のPCで行ってください。

## JSON形式のMCPクライアント

「接続 → MCP設定をコピー」で、現在の場所に合ったJSONを取得できます。

```json
{
  "mcpServers": {
    "mcpaint": {
      "command": "C:\\Tools\\MCPaint\\MCPaint-MCP.exe",
      "args": []
    }
  }
}
```

stdioとPNG画像結果に対応するローカルMCPクライアントが対象です。Web版ChatGPTにlocalhostを直接渡しても、クラウドからPC内のMCPへ接続はできません。このプロジェクトは外部公開用トンネルやOAuthサーバーを提供しません。

## 画像を見ながら描く

1. `screenshot(grid=true)` で現在のキャンバスと座標を確認します。
2. `add_layer` / `select_layer` と `set_brush` で描く場所・色・太さを選びます。
3. `draw_stroke` に点列を渡します。各点は `x`, `y`, `pressure`, `t_ms` です。
4. 返されたPNGを見て、次の線を計画します。必要なら `screenshot(crop=[x,y,w,h])` で拡大確認します。
5. `save_project`、`export_png`、`export_timelapse` で保存します。

点の座標は常に元キャンバスのピクセルです。画像を縮小した場合は `image_info.canvas_pixels_per_image_pixel`、切り取った場合は `image_info.origin` を使います。画面のズームやウィンドウ位置に左右されません。

`expected_revision`に直前の画像が返した版番号を入れると、別の描画が挟まった際の誤操作を防げます。手で線を引いている最中のMCP変更操作はエラーを返します。

```json
{
  "points": [
    {"x": 100, "y": 100, "pressure": 0.3, "t_ms": 0},
    {"x": 130, "y": 115, "pressure": 0.8, "t_ms": 120},
    {"x": 170, "y": 120, "pressure": 0.4, "t_ms": 280}
  ],
  "color": "#3269bf",
  "size": 6
}
```

同じキャンバス上の手動描画とMCP描画は、同じプロジェクトと制作記録に入ります。保存先には、そのPCの絶対パスを指定してください。

設定形式の公式資料: https://developers.openai.com/codex/mcp/
