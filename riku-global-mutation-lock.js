/* RIKU FOOTBALL LAB: cross-tab mutation lock and crash-safe restore journal. */
(function () {
  "use strict";

  const DB_NAME = "rikuFootballLabVideos";
  const LOCK_NAME = "riku-global-mutation-v1";
  const LOCK_KEY = "global-mutation";
  const JOURNAL_HINT_KEY = "rikuMutationJournalHint_v1";
  const JOB_KEY = "rikuVideoRestoreJob_v1";
  const HISTORY_KEY = "rikuVideoBackupHistory_v1";
  const APP_KEY = typeof KEY === "string" ? KEY : "rikuFootballLabData_v1";
  const LEASE_MS = 60000;
  const HEARTBEAT_MS = 15000;
  const protectedKeys = new Set([APP_KEY, JOURNAL_HINT_KEY, JOB_KEY, HISTORY_KEY]);
  let recoveryReady = false;
  let recoveryPromise = null;
  let heartbeat = null;

  function checksum(value) {
    const text = value == null ? "<null>" : String(value);
    let a = 0x811c9dc5, b = 0x9e3779b9;
    for (let i = 0; i < text.length; i++) {
      const c = text.charCodeAt(i);
      a = Math.imul(a ^ c, 0x01000193) >>> 0;
      b = Math.imul(b ^ (c + i), 0x85ebca6b) >>> 0;
    }
    return text.length.toString(36) + "-" + a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
  }
  function makeId(prefix) {
    const random = globalThis.crypto && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
    return prefix + "-" + random;
  }
  function appValue() {
    try { return localStorage.getItem(APP_KEY); } catch (_) { return null; }
  }
  function setNotice(message) {
    const host = document.getElementById("recordSaveNotice");
    if (host) {
      host.textContent = message;
      host.classList.remove("hidden");
    }
    const status = document.getElementById("videoIntegrityResult");
    if (status && window.__rikuMutationSafeMode) {
      status.textContent = message;
    }
  }
  function internalTransaction(db, stores, mode, ctx) {
    const names = Array.from(new Set([].concat(stores, "restoreLocks")));
    window.__rikuLockInternal = true;
    let tx;
    try { tx = db.transaction(names, mode); }
    finally { window.__rikuLockInternal = false; }
    if (ctx) {
      const request = tx.objectStore("restoreLocks").get(LOCK_KEY);
      request.onsuccess = function () {
        const row = request.result;
        if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
          try { tx.abort(); } catch (_) {}
        }
      };
      request.onerror = function () { try { tx.abort(); } catch (_) {} };
    }
    return tx;
  }
  function transactionResult(tx, resultFactory) {
    return new Promise((resolve, reject) => {
      let value;
      if (resultFactory) {
        try { value = resultFactory(tx); } catch (error) { try { tx.abort(); } catch (_) {} reject(error); return; }
      }
      tx.oncomplete = () => resolve(value);
      tx.onerror = () => reject(tx.error || new Error("IndexedDBトランザクションに失敗しました"));
      tx.onabort = () => reject(tx.error || new Error("IndexedDBトランザクションが中断されました"));
    });
  }
  async function openDB() {
    if (typeof window.openVideoDB !== "function") throw new Error("動画データベースを開けません");
    return window.openVideoDB();
  }
  async function acquireFence(ownerId, operationId) {
    const db = await openDB();
    try {
      return await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreLocks"], "readwrite");
        const store = tx.objectStore("restoreLocks");
        const get = store.get(LOCK_KEY);
        let row;
        get.onsuccess = () => {
          const previous = get.result || {};
          row = {
            lockName: LOCK_KEY,
            ownerId,
            operationId,
            fenceToken: Math.max(0, Number(previous.fenceToken) || 0) + 1,
            heartbeatAt: Date.now(),
            leaseUntil: Date.now() + LEASE_MS
          };
          store.put(row);
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = () => resolve(row);
        tx.onerror = () => reject(tx.error || new Error("排他ロックを取得できません"));
        tx.onabort = () => reject(tx.error || new Error("排他ロックの取得が中断されました"));
      });
    } finally { db.close(); }
  }
  async function updateJournal(ctx, patch, journalId) {
    const targetId = journalId || patch.restoreId || ctx.restoreId;
    const changes = { ...patch };
    delete changes.restoreId;
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const get = store.get(targetId);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          Object.assign(row, changes, { updatedAt: new Date().toISOString() });
          store.put(row);
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("復旧ジャーナルを更新できません"));
        tx.onabort = () => reject(tx.error || new Error("復旧ジャーナルの更新が中断されました"));
      });
    } finally { db.close(); }
  }
  async function startJournal(ctx) {
    const db = await openDB();
    try {
      const before = appValue();
      ctx.beforeChecksum = checksum(before);
      ctx.beforeLength = before == null ? null : before.length;
      const row = {
        restoreId: ctx.restoreId,
        operationId: ctx.operationId,
        ownerId: ctx.ownerId,
        fenceToken: ctx.fenceToken,
        operation: ctx.operation,
        state: "prepared",
        beforeStateChecksum: ctx.beforeChecksum,
        beforeStateLength: ctx.beforeLength,
        afterStateChecksum: null,
        afterStateLength: null,
        videoChanges: [],
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const getAll = store.getAll();
        getAll.onsuccess = () => {
          const unresolved = (getAll.result || []).filter(item => !["committed", "rolled-back"].includes(item.state));
          if (unresolved.length) {
            try { tx.abort(); } catch (_) {}
            reject(new Error("未解決の復旧ジャーナルがあります。既存データ保護のため変更を停止しました"));
            return;
          }
          store.put(row);
        };
        getAll.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("復旧ジャーナルを作成できません"));
        tx.onabort = () => reject(tx.error || new Error("復旧ジャーナルの作成が中断されました"));
      });
    } finally { db.close(); }
  }
  async function recordVideoChange(change) {
    const ctx = window.__rikuMutationContext;
    if (!ctx) throw new Error("動画変更にはglobal-mutationロックが必要です");
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const get = store.get(ctx.restoreId);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          row.videoChanges = Array.isArray(row.videoChanges) ? row.videoChanges : [];
          row.videoChanges.push(change);
          row.state = "prepared";
          row.updatedAt = new Date().toISOString();
          store.put(row);
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("動画復旧情報を記録できません"));
        tx.onabort = () => reject(tx.error || new Error("動画復旧情報の記録が中断されました"));
      });
    } finally { db.close(); }
  }
  async function markVideoStage(stage) {
    const ctx = window.__rikuMutationContext;
    if (!ctx) throw new Error("動画変更の所有権を確認できません");
    await updateJournal(ctx, { state: stage });
  }
  async function markVideoOnlyCommit() {
    const ctx = window.__rikuMutationContext;
    if (!ctx || !["storeClipVideo", "restoreClipVideoRecord"].includes(ctx.operation)) return false;
    const value = appValue();
    const sum = checksum(value);
    const length = value == null ? null : value.length;
    localStorage.setItem(JOURNAL_HINT_KEY, JSON.stringify({
      operationId: ctx.operationId, checksum: sum, length,
      state: "video-only-committed", at: Date.now()
    }));
    ctx.afterChecksum = sum;
    ctx.afterLength = length;
    return true;
  }
  async function cancelVideoChange(newPrefix) {
    const ctx = window.__rikuMutationContext;
    if (!ctx) throw new Error("動画変更の所有権を確認できません");
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const get = store.get(ctx.restoreId);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          row.videoChanges = (row.videoChanges || []).filter(change => change.newPrefix !== newPrefix);
          row.updatedAt = new Date().toISOString();
          store.put(row);
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("未確定動画の復旧情報を整理できません"));
        tx.onabort = () => reject(tx.error || new Error("未確定動画の復旧情報整理が中断されました"));
      });
    } finally { db.close(); }
  }
  async function readJournals(db) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction("restoreJournal", "readonly");
      const request = tx.objectStore("restoreJournal").getAll();
      request.onsuccess = () => resolve(request.result || []);
      request.onerror = () => reject(request.error || new Error("復旧ジャーナルを読み取れません"));
      tx.onabort = () => reject(tx.error || new Error("復旧ジャーナルの読み取りが中断されました"));
    });
  }
  async function restoreJournalBefore(ctx, journal) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["videos", "videoChunks", "restoreJournal"], "readwrite", ctx);
        const videos = tx.objectStore("videos");
        const chunks = tx.objectStore("videoChunks");
        const journals = tx.objectStore("restoreJournal");
        const changes = journal.videoChanges || [];
        for (const change of [...changes].reverse()) {
          if (change.oldRecord) videos.put(change.oldRecord, String(change.key));
          else videos.delete(String(change.key));
        }
        const firstByKey = new Map();
        for (const change of changes) if (!firstByKey.has(String(change.key))) firstByKey.set(String(change.key), change);
        const protectedPrefixes = new Set();
        for (const change of firstByKey.values()) {
          if (change.oldPrefix) protectedPrefixes.add(String(change.oldPrefix));
          if (change.oldRecord?.chunkPrefix) protectedPrefixes.add(String(change.oldRecord.chunkPrefix));
        }
        const candidates = new Set(changes.map(change => change.newPrefix).filter(Boolean).map(String));
        const allVideos = videos.getAll();
        allVideos.onsuccess = () => {
          const activePrefixes = new Set((allVideos.result || []).map(row => row?.chunkPrefix).filter(Boolean).map(String));
          for (const prefix of candidates) {
            if (!protectedPrefixes.has(prefix) && !activePrefixes.has(prefix)) {
              chunks.delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
            }
          }
          journals.delete(journal.restoreId);
        };
        allVideos.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("復旧前の動画状態へ戻せません"));
        tx.onabort = () => reject(tx.error || new Error("動画ロールバックが中断されました"));
      });
    } finally { db.close(); }
  }
  async function finishCommittedJournal(ctx, journal) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["videos", "videoChunks", "restoreJournal"], "readwrite", ctx);
        const videos = tx.objectStore("videos");
        const chunks = tx.objectStore("videoChunks");
        const journals = tx.objectStore("restoreJournal");
        const allVideos = videos.getAll();
        const allJournals = journals.getAll();
        let videosReady = false, journalsReady = false, finished = false;
        let videoRows = [], journalRows = [];
        const process = () => {
          if (!videosReady || !journalsReady || finished) return;
          finished = true;
          const changes = journal.videoChanges || [];
          const finalByKey = new Map();
          for (const change of changes) finalByKey.set(String(change.key), change);
          const byKey = new Map((videoRows || []).map(row => [String(row.__key), row]));
          for (const [key, finalChange] of finalByKey) {
            const current = byKey.get(key) || null;
            if (finalChange.kind === "delete" && current) {
              try { tx.abort(); } catch (_) {}
              return;
            }
            if (finalChange.newPrefix && current?.chunkPrefix !== finalChange.newPrefix) {
              try { tx.abort(); } catch (_) {}
              return;
            }
            if (finalChange.kind === "restore" && !finalChange.newPrefix && !current) {
              try { tx.abort(); } catch (_) {}
              return;
            }
          }
          const activePrefixes = new Set(videoRows.map(row => row?.chunkPrefix).filter(Boolean).map(String));
          const candidates = new Set();
          for (const change of changes) {
            if (change.oldPrefix) candidates.add(String(change.oldPrefix));
            if (change.newPrefix) candidates.add(String(change.newPrefix));
          }
          for (const prefix of candidates) {
            if (activePrefixes.has(prefix)) continue;
            const referencedByOtherJournal = journalRows.some(other =>
              other.restoreId !== journal.restoreId &&
              !["committed", "rolled-back"].includes(other.state) &&
              (other.videoChanges || []).some(item => item.oldPrefix === prefix || item.newPrefix === prefix)
            );
            if (!referencedByOtherJournal) {
              chunks.delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
            }
          }
          journals.delete(journal.restoreId);
        };
        allVideos.onsuccess = () => {
          const getKeys = videos.getAllKeys();
          getKeys.onsuccess = () => {
            const values = allVideos.result || [];
            videoRows = values.map((row, index) => ({ ...row, __key: String(getKeys.result[index]) }));
            videosReady = true;
            process();
          };
          getKeys.onerror = () => { try { tx.abort(); } catch (_) {} };
        };
        allVideos.onerror = () => { try { tx.abort(); } catch (_) {} };
        allJournals.onsuccess = () => { journalRows = allJournals.result || []; journalsReady = true; process(); };
        allJournals.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("確定済み動画の後片付けに失敗しました"));
        tx.onabort = () => reject(tx.error || new Error("確定済み動画の後片付けが中断されました"));
      });
    } finally { db.close(); }
  }
  async function releaseFence(ctx) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreLocks"], "readwrite", ctx);
        const store = tx.objectStore("restoreLocks");
        const get = store.get(LOCK_KEY);
        get.onsuccess = () => {
          const row = get.result;
          if (row && row.ownerId === ctx.ownerId && Number(row.fenceToken) === Number(ctx.fenceToken)) {
            store.put({ ...row, ownerId: null, operationId: null, leaseUntil: 0, heartbeatAt: Date.now() });
          }
        };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("排他ロックを解放できません"));
        tx.onabort = () => reject(tx.error || new Error("排他ロックの解放が中断されました"));
      });
    } finally { db.close(); }
  }
  async function heartbeatFence(ctx) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreLocks"], "readwrite", ctx);
        const store = tx.objectStore("restoreLocks");
        const get = store.get(LOCK_KEY);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          store.put({ ...row, heartbeatAt: Date.now(), leaseUntil: Date.now() + LEASE_MS });
        };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("排他ロックの更新に失敗しました"));
        tx.onabort = () => reject(tx.error || new Error("排他ロックの所有権を失いました"));
      });
    } finally { db.close(); }
  }
  async function finalizeOperation(ctx) {
    const db = await openDB();
    let journal;
    try {
      journal = (await readJournals(db)).find(row => row.restoreId === ctx.restoreId);
    } finally { db.close(); }
    if (!journal) return;
    const current = appValue();
    const currentChecksum = checksum(current);
    const hasVideoChanges = Array.isArray(journal.videoChanges) && journal.videoChanges.length > 0;

    if (ctx.forceRollback && currentChecksum === ctx.beforeChecksum) {
      await restoreJournalBefore(ctx, journal);
      return;
    }
    if (ctx.forceRollback && currentChecksum !== ctx.beforeChecksum) {
      await updateJournal(ctx, { state: "recovery-required", reason: "video rollback required after app-state change" });
      window.__rikuMutationSafeMode = true;
      throw new Error("動画の切替を安全に取り消せません。既存データを保持して安全停止しました");
    }
    if (ctx.persistAttempted && !ctx.persisted && currentChecksum === ctx.beforeChecksum) {
      await restoreJournalBefore(ctx, journal);
      return;
    }
    if (hasVideoChanges && !ctx.persisted && ctx.operation !== "storeClipVideo" && ctx.operation !== "restoreClipVideoRecord") {
      if (currentChecksum === ctx.beforeChecksum) {
        await restoreJournalBefore(ctx, journal);
        return;
      }
      await updateJournal(ctx, { state: "recovery-required", reason: "video changed without a confirmed app-state persist" });
      window.__rikuMutationSafeMode = true;
      throw new Error("動画と記録の保存状態が一致しません。既存動画を削除せず安全停止しました");
    }
    if (ctx.persisted && currentChecksum !== ctx.afterChecksum) {
      await updateJournal(ctx, { state: "recovery-required", reason: "localStorage readback checksum mismatch" });
      window.__rikuMutationSafeMode = true;
      throw new Error("保存後の記録照合に失敗しました。動画・履歴を削除せず安全停止しました");
    }
    if (!ctx.persisted && hasVideoChanges && (ctx.operation === "storeClipVideo" || ctx.operation === "restoreClipVideoRecord")) {
      ctx.afterChecksum = currentChecksum;
      ctx.afterLength = current == null ? null : current.length;
      try {
        localStorage.setItem("rikuMutationJournalHint_v1", JSON.stringify({
          operationId: ctx.operationId, checksum: currentChecksum, length: ctx.afterLength,
          state: "video-only-committed", at: Date.now()
        }));
      } catch (error) {
        await updateJournal(ctx, { state: "recovery-required", reason: "video-only commit marker could not be persisted" });
        window.__rikuMutationSafeMode = true;
        throw error;
      }
    }
    if (ctx.persisted || ctx.idbWrites > 0 || ctx.auxStorageMutation) {
      await updateJournal(ctx, {
        state: "persisted",
        afterStateChecksum: (ctx.persisted || (hasVideoChanges && (ctx.operation === "storeClipVideo" || ctx.operation === "restoreClipVideoRecord"))) ? ctx.afterChecksum : null,
        afterStateLength: (ctx.persisted || (hasVideoChanges && (ctx.operation === "storeClipVideo" || ctx.operation === "restoreClipVideoRecord"))) ? ctx.afterLength : null
      });
      const latestDB = await openDB();
      let latest;
      try { latest = (await readJournals(latestDB)).find(row => row.restoreId === ctx.restoreId); }
      finally { latestDB.close(); }
      if (latest) {
        await updateJournal(ctx, { state: "committed" });
        await finishCommittedJournal(ctx, { ...latest, state: "committed" });
      }
      return;
    }
    if (!ctx.persistAttempted && ctx.idbWrites === 0 && !ctx.auxStorageMutation) {
      await restoreJournalBefore(ctx, journal);
      return;
    }
    await updateJournal(ctx, { state: "recovery-required", reason: "operation outcome is ambiguous" });
    window.__rikuMutationSafeMode = true;
  }
  async function runRecovery() {
    if (recoveryReady) return true;
    if (recoveryPromise) return recoveryPromise;
    recoveryPromise = (async () => {
      if (!navigator.locks || typeof navigator.locks.request !== "function") {
        window.__rikuMutationSafeMode = true;
        throw new Error("このSafariでは安全な複数タブ排他制御を利用できません。保存・削除を停止しました");
      }
      await navigator.locks.request(LOCK_NAME, { mode: "exclusive" }, async lock => {
        if (!lock) throw new Error("復旧ロックを取得できません");
        const ownerId = makeId("tab");
        const operationId = makeId("recovery");
        const fence = await acquireFence(ownerId, operationId);
        const ctx = { ownerId, operationId, restoreId: makeId("journal"), fenceToken: fence.fenceToken, operation: "startup-recovery", idbWrites: 0 };
        window.__rikuMutationContext = ctx;
        try {
          const db = await openDB();
          let journals;
          try { journals = await readJournals(db); } finally { db.close(); }
          const currentChecksum = checksum(appValue());
          let hint = null;
          try { hint = JSON.parse(localStorage.getItem(JOURNAL_HINT_KEY) || "null"); } catch (_) {}
          for (const journal of journals) {
            if (journal.state === "committed") {
              await finishCommittedJournal(ctx, journal);
              continue;
            }
            if (journal.state === "rolled-back") continue;
            const afterMatches = hint && hint.operationId === journal.operationId &&
              hint.checksum === currentChecksum &&
              (hint.state === "persisted" || hint.state === "video-only-committed" ||
                (hint.state === "writing" && currentChecksum !== journal.beforeStateChecksum)) &&
              (!journal.afterStateChecksum || journal.afterStateChecksum === currentChecksum);
            if (afterMatches) {
              await updateJournal(ctx, {
                state: "persisted",
                afterStateChecksum: currentChecksum,
                afterStateLength: hint.length == null ? null : Number(hint.length)
              }, journal.restoreId);
              const recovered = { ...journal, state: "committed" };
              await updateJournal(ctx, { state: "committed" }, journal.restoreId);
              await finishCommittedJournal(ctx, recovered);
              continue;
            }
            if (currentChecksum === journal.beforeStateChecksum) {
              await restoreJournalBefore(ctx, journal);
              continue;
            }
            await updateJournal(ctx, {
              state: "recovery-required",
              reason: "localStorage matches neither before nor confirmed after snapshot"
            }, journal.restoreId);
            window.__rikuMutationSafeMode = true;
          }
        } finally {
          window.__rikuMutationContext = null;
          await releaseFence(ctx);
        }
      });
      if (window.__rikuMutationSafeMode) {
        setNotice("復旧ジャーナルの整合性を確認できません。既存動画・分析履歴・pending jobを保護するため、保存・削除を停止しました。バックアップを確保してから確認してください。");
        throw new Error("復旧ジャーナルが未解決です");
      }
      recoveryReady = true;
      return true;
    })().catch(error => {
      window.__rikuMutationSafeMode = true;
      setNotice("保存・削除を安全停止しました：" + (error?.message || String(error)));
      throw error;
    }).finally(() => { recoveryPromise = null; });
    return recoveryPromise;
  }
  window.withGlobalMutationLock = async function (operation, task) {
    if (typeof task !== "function") throw new TypeError("mutation task is required");
    if (window.__rikuMutationContext) return task(window.__rikuMutationContext);
    if (!recoveryReady) await runRecovery();
    if (window.__rikuMutationSafeMode) throw new Error("復旧未完了のためデータ変更を停止しています");
    if (!navigator.locks || typeof navigator.locks.request !== "function") {
      window.__rikuMutationSafeMode = true;
      throw new Error("安全な複数タブ排他制御に対応していません。データ変更を停止しました");
    }
    let output;
    await navigator.locks.request(LOCK_NAME, { mode: "exclusive", ifAvailable: true }, async lock => {
      if (!lock) throw new Error("別のタブで保存処理中です。完了後にもう一度お試しください");
      const ownerId = makeId("tab");
      const operationId = makeId("op");
      const restoreId = makeId("restore");
      const fence = await acquireFence(ownerId, operationId);
      const ctx = { ownerId, operationId, restoreId, fenceToken: fence.fenceToken, operation: String(operation || "mutation"), idbWrites: 0, persistAttempted: false, persisted: false, auxStorageMutation: false };
      window.__rikuMutationContext = ctx;
      try {
        await startJournal(ctx);
        heartbeat = setInterval(() => {
          heartbeatFence(ctx).catch(error => {
            window.__rikuMutationSafeMode = true;
            setNotice("保存処理の所有権を確認できません。変更を停止しました：" + (error?.message || String(error)));
          });
        }, HEARTBEAT_MS);
        output = await task(ctx);
        await finalizeOperation(ctx);
      } catch (error) {
        let recovered = false;
        try {
          await finalizeOperation(ctx);
          recovered = true;
        } catch (recoveryError) {
          try { await updateJournal(ctx, { state: "recovery-required", reason: String(recoveryError?.message || recoveryError).slice(0, 300) }); } catch (_) {}
          window.__rikuMutationSafeMode = true;
          setNotice("処理失敗後の復旧を確認できません。既存動画・分析履歴・pending jobを削除せず安全停止しました");
        }
        if (!recovered) window.__rikuMutationSafeMode = true;
        throw error;
      } finally {
        if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
        window.__rikuMutationContext = null;
        try { await releaseFence(ctx); } catch (error) {
          window.__rikuMutationSafeMode = true;
          setNotice("排他ロックの解放を確認できません。再読み込み前にバックアップを確保してください");
        }
      }
    });
    return output;
  };

  window.__rikuRecordVideoChange = recordVideoChange;
  window.__rikuMarkVideoStage = markVideoStage;
  window.__rikuCancelVideoChange = cancelVideoChange;
  window.__rikuMarkVideoOnlyCommit = markVideoOnlyCommit;
  window.__rikuMutationChecksum = checksum;
  window.__rikuMutationRecoveryReady = () => recoveryReady;

  // Every app write transaction on this database is fenced in the same IDB transaction.
  try {
    const originalTransaction = IDBDatabase.prototype.transaction;
    if (!originalTransaction.__rikuFenced) {
      const guardedTransaction = function (storeNames, mode, options) {
        if (this.name !== DB_NAME || mode !== "readwrite" || window.__rikuLockInternal) {
          return originalTransaction.call(this, storeNames, mode, options);
        }
        const ctx = window.__rikuMutationContext;
        if (!ctx) {
          const denied = originalTransaction.call(this, storeNames, mode, options);
          try { denied.abort(); } catch (_) {}
          return denied;
        }
        const names = typeof storeNames === "string" ? [storeNames] : Array.from(storeNames || []);
        if (!names.includes("restoreLocks")) names.push("restoreLocks");
        const tx = originalTransaction.call(this, names, mode, options);
        const get = tx.objectStore("restoreLocks").get(LOCK_KEY);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
          }
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        ctx.idbWrites = (ctx.idbWrites || 0) + 1;
        return tx;
      };
      guardedTransaction.__rikuFenced = true;
      IDBDatabase.prototype.transaction = guardedTransaction;
    }
  } catch (error) {
    window.__rikuMutationSafeMode = true;
    setNotice("IndexedDBの排他制御を設定できません。データ変更を停止しました");
  }

  // Protect durable app state and Stage 48 checkpoints from unguarded writes.
  try {
    const originalSetItem = Storage.prototype.setItem;
    const originalRemoveItem = Storage.prototype.removeItem;
    const originalClear = Storage.prototype.clear;
    Storage.prototype.setItem = function (key, value) {
      const name = String(key);
      if (this === localStorage && protectedKeys.has(name)) {
        const ctx = window.__rikuMutationContext;
        if (!ctx && !window.__rikuLockInternal) throw new Error("保存にはglobal-mutationロックが必要です");
        if (name === APP_KEY) {
          const serialized = String(value);
          const sum = checksum(serialized);
          if (ctx) { ctx.persistAttempted = true; ctx.persisted = false; ctx.afterChecksum = sum; ctx.afterLength = serialized.length; }
          if (ctx) originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: sum, length: serialized.length, state: "writing", at: Date.now() }));
          const result = originalSetItem.call(this, name, serialized);
          if (ctx) {
            ctx.persisted = true;
            originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: sum, length: serialized.length, state: "persisted", at: Date.now() }));
          }
          return result;
        }
        if (ctx) ctx.auxStorageMutation = true;
      }
      return originalSetItem.call(this, name, value);
    };
    Storage.prototype.removeItem = function (key) {
      const name = String(key);
      if (this === localStorage && protectedKeys.has(name)) {
        const ctx = window.__rikuMutationContext;
        if (!ctx && !window.__rikuLockInternal) throw new Error("削除にはglobal-mutationロックが必要です");
        if (name === APP_KEY && ctx) {
          ctx.persistAttempted = true;
          ctx.persisted = false;
          ctx.afterChecksum = checksum(null);
          ctx.afterLength = null;
          originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: ctx.afterChecksum, length: null, state: "writing", removed: true, at: Date.now() }));
          const result = originalRemoveItem.call(this, name);
          ctx.persisted = true;
          originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: ctx.afterChecksum, length: null, state: "persisted", removed: true, at: Date.now() }));
          return result;
        }
        if (ctx) ctx.auxStorageMutation = true;
      }
      return originalRemoveItem.call(this, name);
    };
    Storage.prototype.clear = function () {
      if (this === localStorage) throw new Error("localStorage.clear()は禁止されています。対象キーを個別に保護してください");
      return originalClear.call(this);
    };
  } catch (error) {
    window.__rikuMutationSafeMode = true;
    setNotice("localStorageの保護を設定できません。データ変更を停止しました");
  }

  const mutationTargets = [
    "updateTrainingStep","saveTraining","addMenu","removeMenu","saveMeasure","deleteItem",
    "scanAndRepairRecordIntegrity","saveClip","setCandidateReview","setCandidateTrackReview","setCandidateTag",
    "saveMatchScanResult","linkMatchEventToTraining","applyMatchImprovementPlan","createCrossMatchHighlight",
    "saveMatchEventEdits","updateMatchPositioning","deleteMatchScan","saveForm","savePlayerProfile","saveSettings",
    "saveApiUrl","saveKickPhaseReview","postVideoToAI","createRikuHighlight","importVideoFiles","clearData",
    "applyAdaptiveCoachPlan","confirmStage23FormIssue","updateGrowthGoalStatus","applyPositionDecisionTraining",
    "applyAlternativeDecisionRetry","applyAlternativeDecisionPractice","updateTrainingWeaponReview",
    "updateMatchWeaponTrial","updateTrainingMatchTransfer","updateTrainingReview","updateWeeklyLoadTeamDay",
    "addWeeklyLoadMatchDate","removeWeeklyLoadMatchDate","applyWeeklyCoachSession","applyCoachTrainingPlan",
    "applyMonthlyTrainingFocus","saveNextMatchGoal","reviewNextMatchGoal","saveAnnualSeasonGoal",
    "toggleMatchdayFocus","updateMatchdayReflection","updatePreMatchHealth","updatePreMatchDate",
    "updatePreMatchPosition","savePreMatchPlan","updatePreMatchReview","updatePostMatchDate",
    "updatePostMatchRecovery","updateRecoveryTrendMode","applyMatchGrowthGoal","markAiFormPhase",
    "saveKickManualReview","deleteAiFormAnalysis","deleteMeasure","storeClipVideo","removeClipVideo",
    "restoreClipVideoRecord","cleanupOrphanedVideoChunks","savePendingMatchJob","clearPendingMatchJob",
    "clearPendingMatchUpload"
  ];
  function wrapMutationTarget(name) {
    const original = window[name];
    if (typeof original !== "function" || original.__rikuMutationWrapped) return;
    const wrapped = function () {
      const self = this, args = arguments;
      if (window.__rikuMutationContext) return original.apply(self, args);
      return window.withGlobalMutationLock(name, () => original.apply(self, args)).catch(error => {
        setNotice((error?.message || String(error)) + "。既存データは削除していません。");
        return false;
      });
    };
    wrapped.__rikuMutationWrapped = true;
    wrapped.__rikuMutationOriginal = original;
    window[name] = wrapped;
  }
  mutationTargets.forEach(wrapMutationTarget);

  // A second user action in this tab must not join an unrelated in-flight operation.
  document.addEventListener("click", event => {
    if (!window.__rikuMutationContext) return;
    if (event.target?.closest?.("#stage48Pause,#stage48Resume,#cancelMatchFingerprintButton")) return;
    if (event.target?.closest?.("button,[onclick],a")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setNotice("保存処理中です。完了または一時停止してから次の操作をしてください");
    }
  }, true);
  document.addEventListener("change", event => {
    if (!window.__rikuMutationContext) return;
    if (event.target?.id === "stage48Pause") return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
  document.addEventListener("submit", event => {
    if (!window.__rikuMutationContext) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  window.addEventListener("load", () => {
    runRecovery().catch(error => console.error("RIKU mutation recovery stopped", error));
  }, { once: true });
})();