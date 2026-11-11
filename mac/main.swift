// LiveBrain Console — macOS 原生壳（WKWebView + 运营热键）
// 构建：./build.sh    运行：./run.sh（自动拉起本地控制台服务）
import Cocoa
import WebKit

let port = 8765
let baseURL = URL(string: "http://127.0.0.1:\(port)")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var retryTimer: Timer?

    func applicationDidFinishLaunching(_ note: Notification) {
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1340, height: 880),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "播控大脑 · 运营控制台"
        window.minSize = NSSize(width: 980, height: 640)

        webView = WKWebView(frame: .zero)
        webView.navigationDelegate = self
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        load()
        buildMenu()
    }

    func load() {
        webView.load(URLRequest(url: baseURL))
    }

    // 服务未就绪时自动重试（run.sh 已尽量等就绪，此处兜底）
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                 withError error: Error) {
        retryTimer?.invalidate()
        retryTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: false) {
            [weak self] _ in self?.load()
        }
    }

    // ---------- 运营热键 -> 控制台 API ----------
    func post(_ action: String) {
        var request = URLRequest(url: URL(string: "\(baseURL)/api/control")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(
            withJSONObject: ["action": action, "params": [:]])
        URLSession.shared.dataTask(with: request) { _, _, _ in }.resume()
    }

    // ---------- 菜单 ----------
    private func menuItem(_ title: String, key: String, alt: Bool = false,
                          sel: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: sel, keyEquivalent: key)
        if alt { item.keyEquivalentModifierMask = [.command, .option] }
        item.target = self
        return item
    }

    func buildMenu() {
        let main = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(menuItem("接管真人", key: "t", sel: #selector(takeover(_:))))
        appMenu.addItem(menuItem("交回 AI", key: "r", alt: true,
                                 sel: #selector(rehandoff(_:))))
        appMenu.addItem(menuItem("恢复 AI（判罚后）", key: "a", alt: true,
                                 sel: #selector(resumeAI(_:))))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(menuItem("重新加载页面", key: "r", sel: #selector(reload(_:))))
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(menuItem("退出", key: "q",
                                 sel: #selector(quit(_:))))
        let appItem = NSMenuItem()
        appItem.submenu = appMenu
        main.addItem(appItem)

        NSApplication.shared.mainMenu = main
    }

    @objc func takeover(_ sender: Any?) { post("takeover") }
    @objc func rehandoff(_ sender: Any?) { post("rehandoff") }
    @objc func resumeAI(_ sender: Any?) { post("resume") }
    @objc func reload(_ sender: Any?) { load() }
    @objc func quit(_ sender: Any?) { NSApplication.shared.terminate(nil) }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.activate(ignoringOtherApps: true)
app.run()
