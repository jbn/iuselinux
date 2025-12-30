import Foundation

let home = ProcessInfo.processInfo.environment["HOME"] ?? ""
let paths = [
    "\(home)/.local/bin",
    "\(home)/.pyenv/shims",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin"
]

func findExecutable(_ name: String) -> String? {
    for dir in paths {
        let path = "\(dir)/\(name)"
        if FileManager.default.isExecutableFile(atPath: path) {
            return path
        }
    }
    return nil
}

func runAndWait(_ executable: String, _ arguments: [String]) -> Int32 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments

    signal(SIGTERM, SIG_IGN)
    let sigSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    sigSource.setEventHandler { process.terminate() }
    sigSource.resume()

    do {
        try process.run()
        process.waitUntilExit()
        return process.terminationStatus
    } catch {
        fputs("Error launching: \(error)\n", stderr)
        return 1
    }
}

var status: Int32 = 1
if let exe = findExecutable("iuselinux") {
    status = runAndWait(exe, ["tray", "run"])
} else if let uvx = findExecutable("uvx") {
    status = runAndWait(uvx, ["iuselinux", "tray", "run"])
} else if let python = findExecutable("python3") {
    status = runAndWait(python, ["-m", "iuselinux", "tray", "run"])
} else {
    fputs("Error: Could not find iuselinux, uvx, or python3 in PATH\n", stderr)
}
exit(status)
