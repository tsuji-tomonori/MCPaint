# MCPaint

Windows PC上で動く、MCP対応のペイントアプリです。人が手で描く場合も、CodexなどのAIが操作する場合も、同じキャンバスとレイヤーを使います。AIは操作後の画像を見ながら次の線を計画できます。

![MCPaintの画面](docs/screenshot.png)

## ダウンロードして起動

1. GitHub Releasesから `MCPaint-0.1.0-windows-x64.zip` をダウンロードします。
2. ZIP全体を任意のフォルダーに展開します。
3. `MCPaint.exe` をダブルクリックします。

Windows 10/11の64bit版が対象です。PythonやFFmpegのインストールは不要です。`_internal` は実行に必要なので、EXEだけを移動せずフォルダー全体を保持してください。現時点の配布版はコード署名していません。

## 描く・保存する

- ペン、鉛筆、マーカー、エアブラシ、消しゴムを選択できます。
- 色、太さ、濃さを変更できます。ペンタブレットの筆圧に対応します。
- 最大64レイヤー。追加、削除、名前変更、上下移動、表示切替、不透明度、ロックを扱えます。
- `Ctrl+Z`で取り消し、`Ctrl+Y`でやり直し。ホイールで拡大、中ボタンで表示位置を移動します。
- `.mcpaint`に、編集可能なレイヤーと制作履歴を保存できます。
- PNGに完成画像、MP4/GIFにタイムラプスを書き出せます。MCPでは背景透過PNGも出力できます。

制作過程は起動中ずっと自動記録します。ストロークごとの座標、筆圧、経過時間、レイヤー操作、取り消し・やり直しを保存します。タイムラプスはこの記録を再描画して生成します。デスクトップ全体の画面録画ではありません。待ち時間を圧縮し、線が伸びる途中も再生します。

現在の編集内容はユーザーホームの `.mcpaint/autosave.mcpaint` に自動保存され、次回起動時に復元します。新規作成や別プロジェクトを開く際は、前の作品を `.mcpaint/checkpoints/` に退避します。通常のプロジェクト保存も併用してください。

## Codexから使う

Windows側のCodex CLIで、展開したフォルダーを指定して登録します。

```powershell
codex mcp add mcpaint -- "C:\Tools\MCPaint\MCPaint-MCP.exe"
```

新しいCodexセッションを開き、例えば次のように依頼します。

> MCPaintの画面を見て、青いペンで猫を描いて。線を少し描くごとに返された画像を確認し、最後にプロジェクトとPNGとタイムラプスを保存して。

アプリが起動していなければ、MCP接続時の最初の操作で起動します。詳しい設定、WSL、他のMCPクライアントについては [docs/mcp-setup.md](docs/mcp-setup.md) を参照してください。

## 開発

```bash
uv sync --frozen --extra dev
uv run python -m mcpaint
uv run python -m mcpaint --mcp
uv run pytest -q
uv run ruff check src tests scripts
```

Linuxのヘッドレス環境でテストする場合は `QT_QPA_PLATFORM=offscreen` を指定してください。

Windowsで `uv run python -m PyInstaller --noconfirm MCPaint.spec` を実行すると配布用フォルダーを生成します。GitHubのmainへ最初にコードを登録すると、ActionsがWindows上でテスト、ビルド、EXEの起動検査を行い、成功した配布ファイルを `v0.1.0` のReleaseへ公開します。その後のmain更新でもビルドし、Actionsの成果物として保存します。既存Releaseは書き換えません。新しい版の公開はタグのpush、またはActionsの手動実行で行います。

## 現在の範囲

キャンバスは最大4096×4096px、レイヤーは64枚、1本の線は最大20,000点です。タイムラプス出力は最長360フレーム・長辺960pxで、録画時間を圧縮します。PSD、画像読み込み、選択範囲編集、テキスト、塗りつぶし、ブラシの追加には対応していません。

MCPはstdio経由で、同じPCのGUIへ認証付きlocalhost接続を使います。外部ホストへの通信は行いません。標準のWeb版ChatGPTからPC内のstdioサーバーへ直接接続する設定は、このアプリに含まれていません。
