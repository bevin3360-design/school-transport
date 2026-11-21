(function () {
  const databaseName = 'sts-driver-location-queue';
  const storeName = 'updates';
  let databasePromise;

  function openDatabase() {
    if (databasePromise) return databasePromise;
    if (!window.indexedDB) {
      return Promise.reject(new Error('IndexedDB is unavailable on this device.'));
    }

    databasePromise = new Promise((resolve, reject) => {
      const request = window.indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => {
        const database = request.result;
        const store = database.objectStoreNames.contains(storeName)
          ? request.transaction.objectStore(storeName)
          : database.createObjectStore(storeName, {
            keyPath: 'id',
            autoIncrement: true
          });
        if (!store.indexNames.contains('owner_id')) {
          store.createIndex('owner_id', 'owner_id', {unique: false});
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => {
          database.close();
          databasePromise = null;
        };
        resolve(database);
      };
      request.onerror = () => {
        databasePromise = null;
        reject(request.error || new Error('Could not open the GPS update queue.'));
      };
      request.onblocked = () => {
        databasePromise = null;
        reject(new Error('GPS update queue is blocked by another open tab.'));
      };
    });

    return databasePromise;
  }

  function finishTransaction(transaction, resolve, reject, result) {
    transaction.oncomplete = () => resolve(
      typeof result === 'function' ? result() : result
    );
    transaction.onerror = () => reject(
      transaction.error || new Error('GPS update queue transaction failed.')
    );
    transaction.onabort = () => reject(
      transaction.error || new Error('GPS update queue transaction was aborted.')
    );
  }

  async function enqueue(ownerId, payload) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(storeName, 'readwrite');
      transaction.objectStore(storeName).add({
        owner_id: String(ownerId),
        payload
      });
      finishTransaction(transaction, resolve, reject);
    });
  }

  async function first(ownerId) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(storeName, 'readonly');
      const request = transaction.objectStore(storeName)
        .index('owner_id')
        .openCursor(window.IDBKeyRange.only(String(ownerId)));
      let result = null;
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor) result = {id: cursor.primaryKey, payload: cursor.value.payload};
      };
      request.onerror = () => reject(
        request.error || new Error('Could not read the GPS update queue.')
      );
      finishTransaction(transaction, resolve, reject, () => result);
    });
  }

  async function remove(id) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(storeName, 'readwrite');
      transaction.objectStore(storeName).delete(id);
      finishTransaction(transaction, resolve, reject);
    });
  }

  async function count(ownerId) {
    const database = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction(storeName, 'readonly');
      const request = transaction.objectStore(storeName)
        .index('owner_id')
        .count(window.IDBKeyRange.only(String(ownerId)));
      let result = 0;
      request.onsuccess = () => {
        result = request.result;
      };
      request.onerror = () => reject(
        request.error || new Error('Could not count the GPS update queue.')
      );
      finishTransaction(transaction, resolve, reject, () => result);
    });
  }

  async function sendNext(ownerId, send) {
    const queued = await first(ownerId);
    if (!queued) return {queued: false, response: null};
    const response = await send(queued.payload);
    if (response.ok) await remove(queued.id);
    return {queued: true, response};
  }

  window.GPSLocationQueue = Object.freeze({
    enqueue, first, remove, count, sendNext
  });
})();
