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
  let originalSetItem = null;
  let originalRemoveItem = null;
  let originalClear = null;

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
  function videoRecordSummary(record) {
    if (!record) return null;
    const blobData = record.blobData;
    const summary = {
      storageFormat: record.storageFormat || null,
      chunkPrefix: record.chunkPrefix || null,
      chunkCount: Number(record.chunkCount) || null,
      size: Number(record.size) || (record.blob instanceof Blob ? record.blob.size : null),
      name: record.name || null,
      type: record.type || null,
      blobType: record.blobType || null,
      lastModified: Number(record.lastModified) || 0,
      blobSize: record.blob instanceof Blob ? record.blob.size : null,
      blobDataBytes: blobData instanceof ArrayBuffer ? blobData.byteLength :
        (ArrayBuffer.isView(blobData) ? blobData.byteLength : null)
    };
    if (Array.isArray(record.chunkSha256)) {
      summary.chunkSha256 = record.chunkSha256.map(value => String(value).toLowerCase());
    }
    return summary;
  }
  function journalDigest(row) {
    const canonical = {
      restoreId: row.restoreId,
      operationId: row.operationId,
      ownerId: row.ownerId,
      fenceToken: Number(row.fenceToken),
      operation: row.operation,
      state: row.state,
      beforeStateChecksum: row.beforeStateChecksum,
      beforeStateLength: row.beforeStateLength,
      afterStateChecksum: row.afterStateChecksum,
      afterStateLength: row.afterStateLength,
      videoChanges: (row.videoChanges || []).map(change => ({
        key: String(change.key), kind: change.kind || null,
        oldPrefix: change.oldPrefix || null, newPrefix: change.newPrefix || null,
        oldRecord: videoRecordSummary(change.oldRecord),
        newRecord: videoRecordSummary(change.newRecord)
      }))
    };
    return checksum(JSON.stringify(canonical));
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
  function internalTransaction(db, stores, mode, ctx, allowExpired) {
    const names = Array.from(new Set([].concat(stores, "restoreLocks")));
    window.__rikuLockInternal = true;
    let tx;
    try { tx = db.transaction(names, mode); }
    finally { window.__rikuLockInternal = false; }
    if (ctx) {
      const request = tx.objectStore("restoreLocks").get(LOCK_KEY);
      request.onsuccess = function () {
        const row = request.result;
        if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken) ||
            (!allowExpired && Number(row.leaseUntil) <= Date.now())) {
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
          const recoveryOwner = ctx.operation === "startup-recovery";
          if (!row || (!recoveryOwner &&
              (row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken))) ||
              row.journalChecksum !== journalDigest(row)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          Object.assign(row, changes, { updatedAt: new Date().toISOString() });
          if (recoveryOwner) {
            // Rebind only under the current, transaction-verified recovery fence.
            row.ownerId = ctx.ownerId;
            row.fenceToken = ctx.fenceToken;
          }
          row.journalChecksum = journalDigest(row);
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
      row.journalChecksum = journalDigest(row);
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const getAll = store.getAll();
        getAll.onsuccess = () => {
          const existingRows = getAll.result || [];
          if (existingRows.some(item => item.journalChecksum !== journalDigest(item))) {
            try { tx.abort(); } catch (_) {}
            reject(new Error("既存の復旧ジャーナルが破損しています。データ変更を停止しました"));
            return;
          }
          const unresolved = existingRows.filter(item => !["committed", "rolled-back"].includes(item.state));
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
    const key = String(change.key);
    for (const prefix of [change.oldPrefix, change.newPrefix].filter(Boolean)) {
      if (!String(prefix).startsWith(key + "|") || !String(prefix).endsWith("|")) {
        throw new Error("動画世代の保存キーが一致しないため、削除・切替を停止しました");
      }
    }
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreJournal"], "readwrite", ctx);
        const store = tx.objectStore("restoreJournal");
        const get = store.get(ctx.restoreId);
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken) ||
              row.journalChecksum !== journalDigest(row)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          row.videoChanges = Array.isArray(row.videoChanges) ? row.videoChanges : [];
          row.videoChanges.push(change);
          row.state = "prepared";
          row.updatedAt = new Date().toISOString();
          row.journalChecksum = journalDigest(row);
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
    if (window.__rikuMutationSafeMode || Number(ctx.leaseUntil) <= Date.now()) {
      throw new Error("動画のみの保存確定前にロック期限を確認できなくなりました");
    }
    const value = appValue();
    const sum = checksum(value);
    const length = value == null ? null : value.length;
    originalSetItem.call(localStorage, JOURNAL_HINT_KEY, JSON.stringify({
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
          row.journalChecksum = journalDigest(row);
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
      request.onsuccess = () => {
        const rows = request.result || [];
        if (rows.some(row => row.journalChecksum !== journalDigest(row))) {
          reject(new Error("復旧ジャーナルのチェックサムが一致しません。既存データ保護のため安全停止しました"));
          try { tx.abort(); } catch (_) {}
          return;
        }
        resolve(rows);
      };
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
        ctx.videoMetadataDeleteAuthorized = true;
        ctx.videoMetadataWriteAuthorized = true;
        try {
          for (const change of [...changes].reverse()) {
            if (change.oldRecord) videos.put(change.oldRecord, String(change.key));
            else videos.delete(String(change.key));
          }
        } finally {
          ctx.videoMetadataDeleteAuthorized = false;
          ctx.videoMetadataWriteAuthorized = false;
        }
        const firstByKey = new Map();
        for (const change of changes) if (!firstByKey.has(String(change.key))) firstByKey.set(String(change.key), change);
        const protectedPrefixes = new Set();
        for (const change of firstByKey.values()) {
          if (change.oldPrefix) protectedPrefixes.add(String(change.oldPrefix));
          if (change.oldRecord?.chunkPrefix) protectedPrefixes.add(String(change.oldRecord.chunkPrefix));
        }
        const candidates = new Set(changes.map(change => change.newPrefix).filter(Boolean).map(String));
        const allJournals = journals.getAll();
        allJournals.onsuccess = () => {
          const rows = allJournals.result || [];
          if (rows.some(row => row.journalChecksum !== journalDigest(row))) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          ctx.chunkDeleteAuthorized = true;
          try {
            for (const prefix of candidates) {
              if (protectedPrefixes.has(prefix)) continue;
              const referencedElsewhere = rows.some(other =>
                other.restoreId !== journal.restoreId &&
                (other.videoChanges || []).some(change => change.oldPrefix === prefix || change.newPrefix === prefix)
              );
              if (!referencedElsewhere) chunks.delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
            }
          } finally { ctx.chunkDeleteAuthorized = false; }
          journals.delete(journal.restoreId);
        };
        allJournals.onerror = () => { try { tx.abort(); } catch (_) {} };
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("復旧前の動画状態へ戻せません"));
        tx.onabort = () => reject(tx.error || new Error("動画ロールバックが中断されました"));
      });
    } finally { db.close(); }
  }
  async function finishCommittedJournal(ctx, journal) {
    const db = await openDB();
    const fail = message => new Error(message);
    const readSnapshot = async () => new Promise((resolve, reject) => {
      const tx = db.transaction(["videos", "restoreJournal", "restoreLocks"], "readonly");
      const journals = tx.objectStore("restoreJournal");
      const requests = {
        journal: journals.get(journal.restoreId),
        journals: journals.getAll(),
        lock: tx.objectStore("restoreLocks").get(LOCK_KEY),
        videos: new Map()
      };
      const keys = [...new Set((journal.videoChanges || []).map(change => String(change.key)))];
      for (const key of keys) requests.videos.set(key, tx.objectStore("videos").get(key));
      const values = { videos: new Map() };
      let remaining = 3 + keys.length;
      const done = () => { remaining--; };
      requests.journal.onsuccess = () => { values.journal = requests.journal.result || null; done(); };
      requests.journals.onsuccess = () => { values.journals = requests.journals.result || []; done(); };
      requests.lock.onsuccess = () => { values.lock = requests.lock.result || null; done(); };
      for (const [key, request] of requests.videos) {
        request.onsuccess = () => { values.videos.set(key, request.result || null); done(); };
        request.onerror = () => { try { tx.abort(); } catch (_) {} };
      }
      requests.journal.onerror = requests.journals.onerror = requests.lock.onerror = () => {
        try { tx.abort(); } catch (_) {}
      };
      tx.oncomplete = () => {
        if (remaining !== 0) { reject(fail("動画削除前の整合性スナップショットが不完全です")); return; }
        resolve(values);
      };
      tx.onerror = () => reject(tx.error || fail("動画削除前の整合性確認に失敗しました"));
      tx.onabort = () => reject(tx.error || fail("動画削除前の整合性確認が中断されました"));
    });
    const readChunk = async key => new Promise((resolve, reject) => {
      const tx = db.transaction("videoChunks", "readonly");
      const request = tx.objectStore("videoChunks").get(key);
      let value = null;
      request.onsuccess = () => { value = request.result == null ? null : request.result; };
      request.onerror = () => { try { tx.abort(); } catch (_) {} };
      tx.oncomplete = () => resolve(value);
      tx.onerror = () => reject(tx.error || fail("動画チャンクの読み取りに失敗しました"));
      tx.onabort = () => reject(tx.error || fail("動画チャンクの読み取りが中断されました"));
    });
    const bytesOf = async value => {
      if (value instanceof Blob) return new Uint8Array(await value.arrayBuffer());
      if (value instanceof ArrayBuffer) return new Uint8Array(value);
      if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
      throw fail("動画チャンクの保存形式が不正です");
    };
    const sha256 = async bytes => {
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, "0")).join("");
    };
    const verifyPrefix = async (prefix, record) => {
      const hashes = record && record.chunkSha256;
      const count = Number(record && record.chunkCount);
      const size = Number(record && record.size);
      if (!Array.isArray(hashes) || !Number.isSafeInteger(count) || count < 1 ||
          hashes.length !== count || !Number.isSafeInteger(size) || size < 1 ||
          hashes.some(value => !/^[0-9a-f]{64}$/i.test(String(value)))) {
        throw fail("期待SHA256がない旧動画世代は削除できません");
      }
      let total = 0;
      for (let index = 0; index < count; index++) {
        const key = prefix + String(index).padStart(8, "0");
        const stored = await readChunk(key);
        if (stored == null) throw fail("検証対象の動画チャンクが不足しています");
        const bytes = await bytesOf(stored);
        const expectedLength = Math.min(1024 * 1024, size - index * 1024 * 1024);
        if (expectedLength <= 0 || bytes.byteLength !== expectedLength) {
          throw fail("動画チャンクのサイズが一致しません");
        }
        const actualHash = await sha256(bytes);
        if (actualHash !== String(hashes[index]).toLowerCase()) {
          throw fail("動画チャンクのSHA256が一致しません");
        }
        total += bytes.byteLength;
      }
      if (total !== size) throw fail("動画世代の合計サイズが一致しません");
    };
    try {
      const snapshot = await readSnapshot();
      const currentJournal = snapshot.journal;
      if (!currentJournal || currentJournal.ownerId !== ctx.ownerId ||
          Number(currentJournal.fenceToken) !== Number(ctx.fenceToken) ||
          currentJournal.state !== "committed" ||
          currentJournal.journalChecksum !== journalDigest(currentJournal)) {
        throw fail("削除前にジャーナル所有者・状態・チェックサムが変化しました");
      }
      if (snapshot.journals.some(row => row.journalChecksum !== journalDigest(row))) {
        throw fail("別の復旧ジャーナルが破損しているため削除を停止しました");
      }
      const lock = snapshot.lock;
      if (!lock || lock.ownerId !== ctx.ownerId ||
          Number(lock.fenceToken) !== Number(ctx.fenceToken) ||
          Number(lock.leaseUntil) <= Date.now()) {
        throw fail("削除前にfence所有権または期限を確認できません");
      }

      const changes = currentJournal.videoChanges || [];
      const byKey = new Map();
      for (const change of changes) {
        const key = String(change.key);
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key).push(change);
      }
      const entries = [...byKey.entries()];
      const deletionCandidates = new Map();
      const expectedCurrent = new Map();
      for (const [key, keyChanges] of entries) {
        const current = snapshot.videos.get(key) || null;
        const finalChange = keyChanges[keyChanges.length - 1];
        if (finalChange.kind === "delete" && current) throw fail("削除対象の動画メタデータが残っています");
        if (finalChange.newPrefix && current?.chunkPrefix !== finalChange.newPrefix) {
          throw fail("動画世代が切り替わっているため削除を停止しました");
        }
        if (finalChange.kind === "restore" && !finalChange.newPrefix &&
            (!current || (finalChange.newRecord &&
              JSON.stringify(videoRecordSummary(current)) !== JSON.stringify(videoRecordSummary(finalChange.newRecord))))) {
          throw fail("復元対象の動画メタデータが一致しません");
        }
        expectedCurrent.set(key, current);
        const candidates = new Map();
        for (const change of keyChanges) {
          if (change.oldPrefix) candidates.set(String(change.oldPrefix), change.oldRecord || null);
          if (change.newPrefix) candidates.set(String(change.newPrefix), change.newRecord || null);
        }
        const activePrefix = current?.chunkPrefix ? String(current.chunkPrefix) : "";
        for (const [prefix, record] of candidates) {
          const expectedRecord = prefix === activePrefix ? current : record;
          const referencedElsewhere = snapshot.journals.some(other =>
            other.restoreId !== currentJournal.restoreId &&
            (other.videoChanges || []).some(item => item.oldPrefix === prefix || item.newPrefix === prefix)
          );
          if (!referencedElsewhere || prefix === activePrefix) {
            await verifyPrefix(prefix, expectedRecord);
            if (prefix !== activePrefix && !referencedElsewhere) deletionCandidates.set(prefix, true);
          }
        }
      }

      // All asynchronous hashing above ran after each readonly transaction completed.
      // Re-fetch every authority and generation in one new write transaction before deleting.
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["videos", "videoChunks", "restoreJournal", "restoreLocks"], "readwrite", ctx);
        let failure = null;
        const abort = message => {
          failure = fail(message);
          try { tx.abort(); } catch (_) {}
        };
        const journalReq = tx.objectStore("restoreJournal").get(currentJournal.restoreId);
        const journalsReq = tx.objectStore("restoreJournal").getAll();
        const lockReq = tx.objectStore("restoreLocks").get(LOCK_KEY);
        const videoReqs = new Map();
        for (const key of expectedCurrent.keys()) videoReqs.set(key, tx.objectStore("videos").get(key));
        let remaining = 3 + videoReqs.size;
        let latestJournal, latestJournals, latestLock;
        const latestVideos = new Map();
        const ready = () => {
          remaining--;
          if (remaining !== 0) return;
          if (!latestJournal || latestJournal.ownerId !== ctx.ownerId ||
              Number(latestJournal.fenceToken) !== Number(ctx.fenceToken) ||
              latestJournal.state !== "committed" ||
              latestJournal.journalChecksum !== currentJournal.journalChecksum ||
              latestJournal.journalChecksum !== journalDigest(latestJournal)) {
            abort("ハッシュ計算中にジャーナルのowner/fence/checksumが変化しました");
            return;
          }
          if (!latestLock || latestLock.ownerId !== ctx.ownerId ||
              Number(latestLock.fenceToken) !== Number(ctx.fenceToken) ||
              Number(latestLock.leaseUntil) <= Date.now()) {
            abort("ハッシュ計算中にfence所有権が変化しました");
            return;
          }
          if (latestJournals.some(row => row.journalChecksum !== journalDigest(row))) {
            abort("削除直前に別の復旧ジャーナルの整合性が崩れました");
            return;
          }
          for (const [key, previous] of expectedCurrent) {
            const latest = latestVideos.get(key) || null;
            if (JSON.stringify(videoRecordSummary(latest)) !== JSON.stringify(videoRecordSummary(previous))) {
              abort("ハッシュ計算中に動画世代・generationが変化しました");
              return;
            }
          }
          ctx.chunkDeleteAuthorized = true;
          try {
            for (const prefix of deletionCandidates.keys()) {
              const referencedElsewhere = latestJournals.some(other =>
                other.restoreId !== latestJournal.restoreId &&
                (other.videoChanges || []).some(item => item.oldPrefix === prefix || item.newPrefix === prefix)
              );
              if (!referencedElsewhere) {
                tx.objectStore("videoChunks").delete(IDBKeyRange.bound(prefix, prefix + "\uffff"));
              }
            }
            tx.objectStore("restoreJournal").delete(latestJournal.restoreId);
          } catch (error) {
            abort(error?.message || "旧動画チャンクの削除要求に失敗しました");
          } finally {
            ctx.chunkDeleteAuthorized = false;
          }
        };
        journalReq.onsuccess = () => { latestJournal = journalReq.result || null; ready(); };
        journalsReq.onsuccess = () => { latestJournals = journalsReq.result || []; ready(); };
        lockReq.onsuccess = () => { latestLock = lockReq.result || null; ready(); };
        for (const [key, request] of videoReqs) {
          request.onsuccess = () => { latestVideos.set(key, request.result || null); ready(); };
          request.onerror = () => abort("削除直前の動画世代を再取得できません");
        }
        journalReq.onerror = journalsReq.onerror = lockReq.onerror = () => abort("削除直前の所有権・ジャーナルを再取得できません");
        tx.oncomplete = resolve;
        tx.onerror = () => reject(failure || tx.error || fail("確定済み動画の後片付けに失敗しました"));
        tx.onabort = () => reject(failure || tx.error || fail("確定済み動画の後片付けが中断されました"));
      });
    } catch (error) {
      ctx.cleanupVerificationFailed = true;
      window.__rikuMutationSafeMode = true;
      throw error;
    } finally {
      ctx.chunkDeleteAuthorized = false;
      db.close();
    }
  }
  async function releaseFence(ctx) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreLocks"], "readwrite", ctx, true);
        const store = tx.objectStore("restoreLocks");
        const get = store.get(LOCK_KEY);
        get.onsuccess = () => {
          const row = get.result;
          if (row && row.ownerId === ctx.ownerId && Number(row.fenceToken) === Number(ctx.fenceToken)) {
            store.put({ ...row, ownerId: null, operationId: null, leaseUntil: 0, heartbeatAt: Date.now() });
          }
        };
        tx.oncomplete = () => { ctx.leaseUntil = 0; resolve(); };
        tx.onerror = () => reject(tx.error || new Error("排他ロックを解放できません"));
        tx.onabort = () => reject(tx.error || new Error("排他ロックの解放が中断されました"));
      });
    } finally { db.close(); }
  }
  async function heartbeatFence(ctx) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = internalTransaction(db, ["restoreLocks"], "readwrite", ctx, true);
        const store = tx.objectStore("restoreLocks");
        const get = store.get(LOCK_KEY);
        let renewedUntil = 0;
        get.onsuccess = () => {
          const row = get.result;
          if (!row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken)) {
            try { tx.abort(); } catch (_) {}
            return;
          }
          renewedUntil = Date.now() + LEASE_MS;
          store.put({ ...row, heartbeatAt: Date.now(), leaseUntil: renewedUntil });
        };
        tx.oncomplete = () => { ctx.leaseUntil = renewedUntil; resolve(); };
        tx.onerror = () => reject(tx.error || new Error("排他ロックの更新に失敗しました"));
        tx.onabort = () => reject(tx.error || new Error("排他ロックの所有権を失いました"));
      });
    } finally { db.close(); }
  }
  async function finalizeOperation(ctx) {
    if (ctx.cleanupVerificationFailed) {
      window.__rikuMutationSafeMode = true;
      throw new Error("動画チャンク検証に失敗したため、同一操作内の後続削除・再試行を禁止しました");
    }
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
        if (window.__rikuMutationSafeMode || Number(ctx.leaseUntil) <= Date.now()) {
          throw new Error("動画のみの保存確定前にロック期限を確認できなくなりました");
        }
        originalSetItem.call(localStorage, JOURNAL_HINT_KEY, JSON.stringify({
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
        try {
          await finishCommittedJournal(ctx, { ...latest, state: "committed" });
        } catch (cleanupError) {
          // A failed committed cleanup is fail-closed: do not retry it from the outer
          // mutation catch, because a transient read failure must never become deletion.
          ctx.committedCleanupFailed = true;
          throw cleanupError;
        }
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
      setNotice("別タブの保存処理・前回の復旧状態を確認しています。完了するまで保存・削除を停止します。");
      if (!navigator.locks || typeof navigator.locks.request !== "function") {
        window.__rikuMutationSafeMode = true;
        throw new Error("このSafariでは安全な複数タブ排他制御を利用できません。保存・削除を停止しました");
      }
      await navigator.locks.request(LOCK_NAME, { mode: "exclusive" }, async lock => {
        if (!lock) throw new Error("復旧ロックを取得できません");
        const ownerId = makeId("tab");
        const operationId = makeId("recovery");
        const fence = await acquireFence(ownerId, operationId);
        const ctx = { ownerId, operationId, restoreId: makeId("journal"), fenceToken: fence.fenceToken, leaseUntil: fence.leaseUntil, operation: "startup-recovery", idbWrites: 0 };
        window.__rikuMutationContext = ctx;
        heartbeat = setInterval(() => {
          heartbeatFence(ctx).catch(error => {
            window.__rikuMutationSafeMode = true;
            setNotice("復旧処理のロックを確認できません。保存・削除を停止しました");
          });
        }, HEARTBEAT_MS);
        try {
          const db = await openDB();
          let journals;
          try { journals = await readJournals(db); } finally { db.close(); }
          const currentChecksum = checksum(appValue());
          let hint = null;
          try { hint = JSON.parse(localStorage.getItem(JOURNAL_HINT_KEY) || "null"); } catch (_) {}
          for (const journal of journals) {
            if (journal.state === "committed") {
              if (journal.afterStateChecksum && currentChecksum !== journal.afterStateChecksum) {
                await updateJournal(ctx, {
                  state: "recovery-required",
                  reason: "committed journal app-state checksum mismatch"
                }, journal.restoreId);
                window.__rikuMutationSafeMode = true;
                throw new Error("確定済みジャーナルと記録データが一致しません。旧動画を削除せず安全停止しました");
              }
              // A committed journal belongs to the previous page's fence.
              // Rebind it to this startup-recovery fence before cleanup verification.
              await updateJournal(ctx, { state: "committed" }, journal.restoreId);
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
            // Stop processing immediately: no later journal may authorize cleanup
            // while an earlier operation has an ambiguous app-state outcome.
            throw new Error("復旧ジャーナルがbefore/afterのどちらとも一致しません。後続の動画削除を停止しました");
          }
        } finally {
          if (heartbeat) { clearInterval(heartbeat); heartbeat = null; }
          window.__rikuMutationContext = null;
          await releaseFence(ctx);
        }
      });
      if (window.__rikuMutationSafeMode) {
        setNotice("復旧ジャーナルの整合性を確認できません。既存動画・分析履歴・pending jobを保護するため、保存・削除を停止しました。バックアップを確保してから確認してください。");
        throw new Error("復旧ジャーナルが未解決です");
      }
      recoveryReady = true;
      const notice = document.getElementById("recordSaveNotice");
      if (notice && notice.textContent.startsWith("別タブの保存処理・前回の復旧状態を確認しています")) {
        notice.classList.add("hidden");
        notice.textContent = "";
      }
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
      const ctx = { ownerId, operationId, restoreId, fenceToken: fence.fenceToken, leaseUntil: fence.leaseUntil, operation: String(operation || "mutation"), idbWrites: 0, persistAttempted: false, persisted: false, persistFailure: false, auxStorageMutation: false };
      try { ctx.stateSnapshot = typeof state === "undefined" ? null : JSON.stringify(state); }
      catch (snapshotError) { await releaseFence(ctx); throw new Error("保存前の状態を安全に退避できません：" + (snapshotError?.message || String(snapshotError))); }
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
        if (ctx.persistFailure && !ctx.persisted && ctx.stateSnapshot) {
          state = JSON.parse(ctx.stateSnapshot);
          if (typeof renderAll === "function") renderAll();
          setNotice("保存に失敗したため、画面上の変更も保存前に戻しました。既存データは維持しています。");
        }
        await finalizeOperation(ctx);
      } catch (error) {
        if (ctx.persistFailure && !ctx.persisted && ctx.stateSnapshot) {
          try { state = JSON.parse(ctx.stateSnapshot); if (typeof renderAll === "function") renderAll(); } catch (_) {}
        }
        let recovered = false;
        if (ctx.committedCleanupFailed) {
          try {
            await updateJournal(ctx, {
              state: "recovery-required",
              reason: "committed cleanup verification failed; retry requires explicit recovery"
            });
          } catch (_) {}
          window.__rikuMutationSafeMode = true;
          setNotice("確定済み動画の削除前検証に失敗しました。旧動画を保持して安全停止しました");
        } else {
          try {
            await finalizeOperation(ctx);
            recovered = true;
          } catch (recoveryError) {
            try { await updateJournal(ctx, { state: "recovery-required", reason: String(recoveryError?.message || recoveryError).slice(0, 300) }); } catch (_) {}
            window.__rikuMutationSafeMode = true;
            setNotice("処理失敗後の復旧を確認できません。既存動画・分析履歴・pending jobを削除せず安全停止しました");
          }
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
    if (!IDBFactory.prototype.deleteDatabase.__rikuVideoDatabaseDeleteGuarded) {
      const originalDeleteDatabase = IDBFactory.prototype.deleteDatabase;
      const guardedDeleteDatabase = function (name) {
        if (String(name) === DB_NAME) {
          throw new Error("動画データベース全体の削除は禁止されています。既存動画・履歴を保護しています");
        }
        return originalDeleteDatabase.call(this, name);
      };
      guardedDeleteDatabase.__rikuVideoDatabaseDeleteGuarded = true;
      IDBFactory.prototype.deleteDatabase = guardedDeleteDatabase;
    }
    if (!IDBObjectStore.prototype.put.__rikuMutationPutGuarded) {
      const originalPut = IDBObjectStore.prototype.put;
      const guardedPut = function (value, key) {
        const ctx = window.__rikuMutationContext;
        if (this.name === "videoChunks" && (!ctx || !ctx.chunkWriteAuthorized)) {
          throw new Error("動画チャンク書き込みは保存ジャーナルで許可された処理に限定されています");
        }
        if (this.name === "videos") {
          if (key === "__pending_match_job__" && (!ctx || !ctx.pendingJobWriteAuthorized)) {
            throw new Error("pending match jobは専用の保存処理以外から更新できません");
          }
          if (key === "__pending_match_upload__" && (!ctx || !ctx.pendingUploadWriteAuthorized)) {
            throw new Error("pending upload情報は専用の保存処理以外から更新できません");
          }
          if (key !== "__pending_match_job__" && key !== "__pending_match_upload__" &&
              (!ctx || !ctx.videoMetadataWriteAuthorized)) {
            throw new Error("動画メタデータ書き込みには復旧ジャーナルが必要です");
          }
        }
        return originalPut.apply(this, arguments);
      };
      guardedPut.__rikuMutationPutGuarded = true;
      IDBObjectStore.prototype.put = guardedPut;
    }
    if (!IDBObjectStore.prototype.add.__rikuMutationAddGuarded) {
      const originalAdd = IDBObjectStore.prototype.add;
      const guardedAdd = function (value, key) {
        const ctx = window.__rikuMutationContext;
        if (this.name === "videoChunks" && (!ctx || !ctx.chunkWriteAuthorized)) {
          throw new Error("動画チャンク追加は保存ジャーナルで許可された処理に限定されています");
        }
        if (this.name === "videos") {
          if (key === "__pending_match_job__" && (!ctx || !ctx.pendingJobWriteAuthorized)) {
            throw new Error("pending match jobは専用の保存処理以外から追加できません");
          }
          if (key === "__pending_match_upload__" && (!ctx || !ctx.pendingUploadWriteAuthorized)) {
            throw new Error("pending upload情報は専用の保存処理以外から追加できません");
          }
          if (key !== "__pending_match_job__" && key !== "__pending_match_upload__" &&
              (!ctx || !ctx.videoMetadataWriteAuthorized)) {
            throw new Error("動画メタデータ追加には復旧ジャーナルが必要です");
          }
        }
        return originalAdd.apply(this, arguments);
      };
      guardedAdd.__rikuMutationAddGuarded = true;
      IDBObjectStore.prototype.add = guardedAdd;
    }
    if (!IDBObjectStore.prototype.delete.__rikuPendingJobGuarded) {
      const originalDelete = IDBObjectStore.prototype.delete;
      const guardedDelete = function (key) {
        if (this.name === "videoChunks") {
          const ctx = window.__rikuMutationContext;
          if (!ctx || !ctx.chunkDeleteAuthorized) {
            throw new Error("動画チャンク削除は復旧ジャーナルで許可された処理に限定されています");
          }
        }
        if (this.name === "videos" && key instanceof IDBKeyRange) {
          throw new Error("動画メタデータの範囲削除は禁止されています");
        }
        if (this.name === "videos" && key === "__pending_match_job__") {
          const ctx = window.__rikuMutationContext;
          if (!ctx || !ctx.pendingJobClearAuthorized) {
            throw new Error("pending match jobは保存済み解析履歴の確認なしに削除できません");
          }
        }
        if (this.name === "videos" && key === "__pending_match_upload__") {
          const ctx = window.__rikuMutationContext;
          if (!ctx || !ctx.pendingUploadClearAuthorized) {
            throw new Error("pending upload情報は専用の復旧処理以外から削除できません");
          }
        }
        if (this.name === "videos" &&
            key !== "__pending_match_job__" && key !== "__pending_match_upload__") {
          const ctx = window.__rikuMutationContext;
          if (!ctx || !ctx.videoMetadataDeleteAuthorized) {
            throw new Error("動画メタデータ削除は復旧ジャーナルで許可された処理に限定されています");
          }
        }
        return originalDelete.call(this, key);
      };
      guardedDelete.__rikuPendingJobGuarded = true;
      IDBObjectStore.prototype.delete = guardedDelete;
    }
    if (!IDBCursor.prototype.update.__rikuMutationCursorGuarded) {
      const originalUpdate = IDBCursor.prototype.update;
      const guardedUpdate = function (value) {
        const source = this.source;
        const storeName = source instanceof IDBObjectStore ? source.name : source?.objectStore?.name;
        const key = this.primaryKey;
        const ctx = window.__rikuMutationContext;
        if (storeName === "videoChunks" && (!ctx || !ctx.chunkWriteAuthorized)) {
          throw new Error("動画チャンク更新は保存ジャーナルで許可された処理に限定されています");
        }
        if (storeName === "videos") {
          if (key === "__pending_match_job__" && (!ctx || !ctx.pendingJobWriteAuthorized)) {
            throw new Error("pending match jobは専用の保存処理以外から更新できません");
          }
          if (key === "__pending_match_upload__" && (!ctx || !ctx.pendingUploadWriteAuthorized)) {
            throw new Error("pending upload情報は専用の保存処理以外から更新できません");
          }
          if (key !== "__pending_match_job__" && key !== "__pending_match_upload__" &&
              (!ctx || !ctx.videoMetadataWriteAuthorized)) {
            throw new Error("動画メタデータ更新には復旧ジャーナルが必要です");
          }
        }
        return originalUpdate.call(this, value);
      };
      guardedUpdate.__rikuMutationCursorGuarded = true;
      IDBCursor.prototype.update = guardedUpdate;
    }
    if (!IDBCursor.prototype.delete.__rikuMutationCursorGuarded) {
      const originalCursorDelete = IDBCursor.prototype.delete;
      const guardedCursorDelete = function () {
        const source = this.source;
        const storeName = source instanceof IDBObjectStore ? source.name : source?.objectStore?.name;
        const key = this.primaryKey;
        const ctx = window.__rikuMutationContext;
        if (storeName === "videoChunks" && (!ctx || !ctx.chunkDeleteAuthorized)) {
          throw new Error("動画チャンク削除は復旧ジャーナルで許可された処理に限定されています");
        }
        if (storeName === "videos") {
          if (key === "__pending_match_job__" && (!ctx || !ctx.pendingJobClearAuthorized)) {
            throw new Error("pending match jobは保存済み解析履歴の確認なしに削除できません");
          }
          if (key === "__pending_match_upload__" && (!ctx || !ctx.pendingUploadClearAuthorized)) {
            throw new Error("pending upload情報は専用の復旧処理以外から削除できません");
          }
          if (key !== "__pending_match_job__" && key !== "__pending_match_upload__" &&
              (!ctx || !ctx.videoMetadataDeleteAuthorized)) {
            throw new Error("動画メタデータ削除は復旧ジャーナルで許可された処理に限定されています");
          }
        }
        return originalCursorDelete.call(this);
      };
      guardedCursorDelete.__rikuMutationCursorGuarded = true;
      IDBCursor.prototype.delete = guardedCursorDelete;
    }
    if (!IDBObjectStore.prototype.clear.__rikuVideoStoreClearGuarded) {
      const originalClear = IDBObjectStore.prototype.clear;
      const guardedClear = function () {
        if (this.name === "videos" || this.name === "videoChunks") {
          throw new Error("動画ストア全体の消去は禁止されています。個別の復旧ジャーナル処理を使用してください");
        }
        return originalClear.call(this);
      };
      guardedClear.__rikuVideoStoreClearGuarded = true;
      IDBObjectStore.prototype.clear = guardedClear;
    }
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
          if (window.__rikuMutationSafeMode || !row || row.ownerId !== ctx.ownerId || Number(row.fenceToken) !== Number(ctx.fenceToken) ||
              Number(row.leaseUntil) <= Date.now()) {
            try { tx.abort(); } catch (_) {}
          }
        };
        get.onerror = () => { try { tx.abort(); } catch (_) {} };
        ctx.idbWriteAttempts = (ctx.idbWriteAttempts || 0) + 1;
        tx.addEventListener("complete", () => { ctx.idbWrites = (ctx.idbWrites || 0) + 1; }, { once: true });
        tx.addEventListener("abort", () => { ctx.idbWriteFailures = (ctx.idbWriteFailures || 0) + 1; }, { once: true });
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
    originalSetItem = Storage.prototype.setItem;
    originalRemoveItem = Storage.prototype.removeItem;
    originalClear = Storage.prototype.clear;
    Storage.prototype.setItem = function (key, value) {
      const name = String(key);
      if (this === localStorage && protectedKeys.has(name)) {
        const ctx = window.__rikuMutationContext;
        if (name === JOURNAL_HINT_KEY) throw new Error("復旧ジャーナルのヒントは内部処理専用です");
        if (!ctx || window.__rikuMutationSafeMode || Number(ctx.leaseUntil) <= Date.now()) {
          throw new Error("保存ロックの期限・所有権を確認できないため保存を停止しました");
        }
        if (name === APP_KEY) {
          const serialized = String(value);
          const sum = checksum(serialized);
          if (ctx) { ctx.persistAttempted = true; ctx.persisted = false; ctx.persistFailure = false; ctx.afterChecksum = sum; ctx.afterLength = serialized.length; }
          try {
            if (ctx) originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: sum, length: serialized.length, state: "writing", at: Date.now() }));
            const result = originalSetItem.call(this, name, serialized);
            if (ctx) {
              ctx.persisted = true;
              originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: sum, length: serialized.length, state: "persisted", at: Date.now() }));
            }
            return result;
          } catch (error) {
            if (ctx) ctx.persistFailure = true;
            throw error;
          }
        }
        if (ctx) ctx.auxStorageMutation = true;
      }
      return originalSetItem.call(this, name, value);
    };
    Storage.prototype.removeItem = function (key) {
      const name = String(key);
      if (this === localStorage && protectedKeys.has(name)) {
        const ctx = window.__rikuMutationContext;
        if (name !== APP_KEY) throw new Error("pending job・履歴・復旧ヒントは専用処理以外から削除できません");
        if (!ctx || window.__rikuMutationSafeMode || Number(ctx.leaseUntil) <= Date.now()) {
          throw new Error("削除ロックの期限・所有権を確認できないため削除を停止しました");
        }
        if (name === APP_KEY && ctx) {
          ctx.persistAttempted = true;
          ctx.persisted = false;
          ctx.persistFailure = false;
          ctx.afterChecksum = checksum(null);
          ctx.afterLength = null;
          try {
            originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: ctx.afterChecksum, length: null, state: "writing", removed: true, at: Date.now() }));
            const result = originalRemoveItem.call(this, name);
            ctx.persisted = true;
            originalSetItem.call(this, JOURNAL_HINT_KEY, JSON.stringify({ operationId: ctx.operationId, checksum: ctx.afterChecksum, length: null, state: "persisted", removed: true, at: Date.now() }));
            return result;
          } catch (error) {
            ctx.persistFailure = true;
            throw error;
          }
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
    "restoreClipVideoRecord","cleanupOrphanedVideoChunks","savePendingMatchUpload","savePendingMatchJob","clearPendingMatchJob",
    "clearPendingMatchUpload"
  ];
  function wrapMutationTarget(name) {
    const original = window[name];
    if (typeof original !== "function" || original.__rikuMutationWrapped) return;
    const wrapped = function () {
      const self = this, args = arguments;
      if (window.__rikuMutationContext) return original.apply(self, args);
      const isAsync = original.constructor && original.constructor.name === "AsyncFunction";
      return window.withGlobalMutationLock(name, () => original.apply(self, args)).catch(error => {
        setNotice((error?.message || String(error)) + "。既存データは削除していません。");
        if (isAsync) throw error;
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