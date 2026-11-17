// Desktop integration: open PDFs and documents in the system viewer when
// running inside Tauri, or in a new browser tab otherwise.
import { api, isTauri, url } from "./api";

export async function openServerFile(exportPath: string, fallbackUrl: string): Promise<void> {
  if (isTauri()) {
    const { path } = await api.post<{ path: string }>(exportPath);
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(path);
  } else {
    window.open(url(fallbackUrl, true), "_blank", "noopener");
  }
}

export async function openDocument(docId: string): Promise<void> {
  if (isTauri()) {
    const { path } = await api.get<{ path: string }>(`/api/documents/${docId}/path`);
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(path);
  } else {
    window.open(url(`/api/documents/${docId}/file`, true), "_blank", "noopener");
  }
}

export async function openFolder(path: string): Promise<void> {
  if (isTauri()) {
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(path);
  }
}
