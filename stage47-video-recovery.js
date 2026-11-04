/* Stage 47: safe, preflighted, batch-atomic video recovery. */
(function () {
  "use strict";
  const PREFIX = "riku-video__";
  const PREVIEW_ID = "videoRestorePreview";

  function previewHost() {
    let host = document.getElementById(PREVIEW_ID);
    if (!host) {
      host = document.createElement("div");
      host.id = PREVIEW_ID;
      host.className = "note";
      host.setAttribute("role", "status");
      host.setAttribute("aria-live", "polite");
      const input = document.getElementById("videoImportFiles");
      if (input && input.parentElement) input.parentElement.insertBefore(host, document.getElementById("videoImportProgress"));
    }
    return host;
  }

  function decodeVideoFilename(file) {
    if (!file.name.startsWith(PREFIX)) throw new Error(file.name + "：書き出し時の紐づけファイル名ではありません");
    const separator = file.name.indexOf("__", PREFIX.length);
    if (separator < 0) throw new Error(file.name + "：ファイル名の形式が不正です");
    let key, name;
    try {
      key = decodeURIComponent(file.name.slice(PREFIX.length, separator));
      name = decodeURIComponent(file.name.slice(separator + 2));
    } catch (_) {
      throw new Error(file.name + "：ファイル名の文字コードが不正です");
    }
    if (!key || key.startsWith("__pending_") || !name) throw new Error(file.name + "：保存キーまたは動画名が不正です");
    const isForm = key.startsWith("form-");
    const id = isForm ? key.slice(5) : key;
    const record = (isForm ? state.forms : state.clips).find(row => String(row.id) === String(id));
    if (!record) throw new Error(file.name + "：対応する分析記録がありません。先にJSONバックアップを読み込んでください");
    if (!(file instanceof Blob) || !Number(file.size)) throw new Error(file.name + "：動画ファイルが空です");
    return { file, key, name, record, kind: isForm ? "フォーム分析" : "プレー分析" };
  }

  function probePlayable(blob) {
    return new Promise((resolve, reject) => {
      const video = document.createElement("video");
      const url = URL.createObjectURL(blob);
      let settled = false;
      const finish = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        video.removeAttribute("src");
        video.load();
        URL.revokeObjectURL(url);
        if (error) reject(error); else resolve({ duration: video.duration, width: video.videoWidth, height: video.videoHeight });
      };
      const timer = setTimeout(() => finish(new Error("動画の再生情報を読み取れません（形式・破損を確認してください）")), 12000);
      video.preload = "metadata";
      video.muted = true;
      video.onloadedmetadata = () => {
        if (!Number.isFinite(video.duration) || video.duration <= 0 || !video.videoWidth || !video.videoHeight) {
          finish(new Error("動画の長さ・映像サイズを確認できません"));
          return;
        }
        finish(null);
      };
      video.onerror = () => finish(new Error("ブラウザで動画を読み取れません。対応形式か破損を確認してください"));
      video.src = url;
      video.load();
    });
  }

  async function snapshotVideoRows(keys) {
    const result = new Map();
    for (const key of keys) result.set(key, await getClipVideo(key));
    return result;
  }

  async function rollbackBatch(originalState, originalStored, originals, changedKeys) {
    const errors = [];
    for (const key of [...changedKeys].reverse()) {
      try {
        const previous = originals.get(key);
        if (previous) await restoreClipVideoRecord(key, previous);
        else await removeClipVideo(key);
      } catch (error) {
        console.error("Stage 47 video rollback failed", key, error);
        errors.push(key);
      }
    }
    state = originalState;
    try {
      if (originalStored === null) localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, originalStored);
    } catch (error) {
      console.error("Stage 47 state rollback failed", error);
      errors.push("記録データ");
    }
    try { renderAll(); } catch (error) { console.error("Stage 47 rollback render failed", error); }
    return errors;
  }

  async function restoreVideoBatch(files) {
    const host = previewHost();
    const rows = [];
    const errors = [];
    const seen = new Map();
    updateVideoTaskProgress("videoImportProgress", "復元前の動画を検査しています…", 2);

    for (const file of files) {
      try {
        const row = decodeVideoFilename(file);
        if (seen.has(row.key)) {
          if (await compareVideoBlobs(seen.get(row.key).file, row.file)) {
            row.duplicateInSelection = true;
            rows.push(row);
            continue;
          }
          throw new Error(file.name + "：同じ保存キーに異なる動画が複数選ばれています");
        }
        seen.set(row.key, row);
        rows.push(row);
      } catch (error) {
        errors.push(error.message || String(error));
      }
    }

    if (errors.length) {
      host.textContent = "復元中止：事前検査で問題が見つかりました。\n" + errors.join("\n") + "\n現在の動画・分析記録は変更していません。";
      updateVideoTaskProgress("videoImportProgress", "事前検査に失敗しました。データは変更していません。", 0);
      alert(host.textContent);
      return;
    }

    const uniqueRows = rows.filter(row => !row.duplicateInSelection);
    const totalBytes = uniqueRows.reduce((sum, row) => sum + Number(row.file.size || 0), 0);
    const originalState = JSON.parse(JSON.stringify(state));
    const originalStored = localStorage.getItem(KEY);
    const keys = [...new Set(uniqueRows.map(row => row.key))];
    const originals = await snapshotVideoRows(keys);
    const collisions = [];
    const exactDuplicates = [];
    const replacementRows = [];

    for (const row of uniqueRows) {
      const existing = originals.get(row.key);
      if (existing?.blob instanceof Blob && existing.blob.size > 0) {
        if (await compareVideoBlobs(existing.blob, row.file)) exactDuplicates.push(row);
        else { collisions.push(row); replacementRows.push(row); }
      } else replacementRows.push(row);
    }

    const probeRows = replacementRows;
    for (let index = 0; index < probeRows.length; index++) {
      const row = probeRows[index];
      updateVideoTaskProgress("videoImportProgress", "動画の再生可能性を事前確認しています… " + (index + 1) + " / " + probeRows.length, Math.round(5 + (index / Math.max(1, probeRows.length)) * 25));
      try { row.media = await probePlayable(row.file); }
      catch (error) { errors.push(row.file.name + "：" + (error.message || String(error))); }
    }
    if (errors.length) {
      host.textContent = "復元中止：動画の事前検査に失敗しました。\n" + errors.join("\n") + "\n既存データは変更していません。";
      updateVideoTaskProgress("videoImportProgress", "動画の事前検査に失敗しました。データは変更していません。", 0);
      alert(host.textContent);
      return;
    }

    let estimateNote = "";
    try {
      if (navigator.storage?.estimate) {
        const estimate = await navigator.storage.estimate();
        const free = Math.max(0, Number(estimate.quota || 0) - Number(estimate.usage || 0));
        if (estimate.quota) {
          estimateNote = "ブラウザ残り容量の目安 " + (free / 1024 / 1024).toFixed(1) + "MB";
          if (totalBytes > free) {
            host.textContent = "復元中止：選択動画の合計サイズがブラウザ残り容量の目安を超えています。\n" + estimateNote + "／必要 " + (totalBytes / 1024 / 1024).toFixed(1) + "MB\n現在のデータは変更していません。";
            updateVideoTaskProgress("videoImportProgress", "保存容量不足の可能性があります。", 0);
            alert(host.textContent);
            return;
          }
        }
      }
    } catch (error) { console.warn("Stage 47 storage estimate unavailable", error); }

    const preview = [
      "復元前プレビュー",
      "対象動画 " + uniqueRows.length + "本／合計 " + (totalBytes / 1024 / 1024).toFixed(1) + "MB",
      "新規復元 " + replacementRows.length + "本／同一動画のためスキップ " + exactDuplicates.length + "本／上書き確認が必要 " + collisions.length + "本",
      "動画形式・再生メタデータの事前確認：成功",
      estimateNote,
      "対象記録：" + uniqueRows.map(row => row.kind + "「" + row.record.title + "」").join("、"),
      collisions.length ? "同じ記録に別動画が存在します。OKで置き換え、キャンセルで中止します。" : "",
      "復元中に失敗した場合は、今回変更した動画と記録情報を元に戻します。"
    ].filter(Boolean).join("\n");
    host.textContent = preview;
    if (!confirm(preview + "\n\nこの内容で復元を開始しますか？")) {
      updateVideoTaskProgress("videoImportProgress", "復元をキャンセルしました。既存データは変更していません。", 0);
      return;
    }

    const changedKeys = new Set();
    let imported = 0;
    let skipped = exactDuplicates.length;
    try {
      for (let index = 0; index < replacementRows.length; index++) {
        const row = replacementRows[index];
        updateVideoTaskProgress("videoImportProgress", "動画を保存・照合しています… " + (index + 1) + " / " + replacementRows.length, Math.round(35 + (index / Math.max(1, replacementRows.length)) * 45));
        const previous = originals.get(row.key);
        if (previous?.blob instanceof Blob && previous.blob.size > 0 && !confirm("同じ記録キーに別の動画が保存されています。\n「" + row.name + "」で置き換えますか？")) {
          throw new Error("既存動画の上書きがキャンセルされました。バッチ全体を元に戻します");
        }
        changedKeys.add(row.key);
        await storeClipVideo(row.key, new File([row.file], row.name, { type: row.file.type || "application/octet-stream", lastModified: row.file.lastModified }));
        const saved = await getClipVideo(row.key);
        if (!saved?.blob || !(await compareVideoBlobs(saved.blob, row.file))) throw new Error(row.name + "：保存後のバイト照合に失敗しました");
        await probePlayable(saved.blob);
        row.record.hasVideo = true;
        imported++;
      }
      for (const row of uniqueRows) row.record.hasVideo = true;
      if (!persist()) throw new Error("動画と分析記録の保存に失敗しました");
      updateVideoTaskProgress("videoImportProgress", "動画の復元・保存・再生情報確認が完了しました。", 100);
      lastVideoImportFiles = [];
      const retryButton = document.getElementById("videoImportRetry");
      if (retryButton) retryButton.style.display = "none";
      if (typeof scanSavedVideoIntegrity === "function") await scanSavedVideoIntegrity();
      if (typeof refreshVideoStorageStatus === "function") refreshVideoStorageStatus();
      host.textContent = preview + "\n\n完了：保存後の動画バイト照合・再生メタデータ確認に成功。再生テストは下の照合結果から実行できます。";
      alert("動画ファイルの復元が完了しました。\n新規保存・確認：" + imported + "本\n同一動画のためスキップ：" + skipped + "本\n未読込：" + errors.length + "本\n保存後の照合・再生メタデータ確認：成功\n設定画面の「動画と記録を照合する」にある「再生テスト」から実際の再生も確認できます。");
    } catch (error) {
      const rollbackErrors = await rollbackBatch(originalState, originalStored, originals, changedKeys);
      lastVideoImportFiles = files;
      const retryButton = document.getElementById("videoImportRetry");
      if (retryButton) retryButton.style.display = "inline-flex";
      const suffix = rollbackErrors.length ? "\nロールバック要確認：" + rollbackErrors.join("、") : "\n今回の変更は元の状態へ戻しました。";
      host.textContent = "復元失敗：" + (error.message || String(error)) + suffix;
      updateVideoTaskProgress("videoImportProgress", "復元に失敗しました。元の状態へロールバックしました。再試行できます。", 0);
      alert(host.textContent);
    }
  }

  window.addEventListener("change", event => {
    if (event.target?.id !== "videoImportFiles") return;
    event.stopImmediatePropagation();
    event.preventDefault();
    const files = [...(event.target.files || [])];
    if (!files.length) return;
    lastVideoImportFiles = files;
    restoreVideoBatch(files).finally(() => { event.target.value = ""; });
  }, true);

  window.retryFailedVideoImport = async function () {
    if (!lastVideoImportFiles?.length) return;
    await restoreVideoBatch([...lastVideoImportFiles]);
  };
  window.runStage47VideoRestore = restoreVideoBatch;
})();
