"use strict";

class ProjectItemCache {
  constructor(normalizePath) {
    this.normalizePath = normalizePath;
    this.projectKey = null;
    this.items = new Map();
    this.initialized = false;
    this.refreshedAt = null;
    this.hits = 0;
    this.misses = 0;
    this.fallbacks = 0;
  }

  useProject(projectKey) {
    if (this.projectKey !== projectKey) this.invalidate(projectKey);
  }

  get(path) {
    const item = this.items.get(this.normalizePath(path));
    if (item) this.hits += 1;
    else this.misses += 1;
    return item || null;
  }

  set(path, item) {
    this.items.set(this.normalizePath(path), item);
    return item;
  }

  markInitialized() {
    this.initialized = true;
    this.refreshedAt = new Date().toISOString();
  }

  markFallback() { this.fallbacks += 1; }

  invalidate(projectKey = this.projectKey) {
    this.projectKey = projectKey;
    this.items.clear();
    this.initialized = false;
    this.refreshedAt = new Date().toISOString();
  }

  diagnostics() {
    return { projectKey: this.projectKey, size: this.items.size, initialized: this.initialized, refreshedAt: this.refreshedAt, hits: this.hits, misses: this.misses, fallbacks: this.fallbacks };
  }
}

module.exports = { ProjectItemCache };

