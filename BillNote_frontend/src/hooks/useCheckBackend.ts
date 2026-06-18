import { useCallback, useEffect, useRef, useState } from 'react'

import { getApiBase } from '@/utils/backendBase'

const TOTAL_TIMEOUT_MS = 60_000
const POLL_INTERVAL_MS = 2_000
const PROBE_TIMEOUT_MS = 5_000

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

interface Status {
  loading: boolean
  initialized: boolean
  failed: boolean
  lastError: string | null
}

interface BackendCheck extends Status {
  retry: () => void
}

const initialStatus: Status = {
  loading: true,
  initialized: false,
  failed: false,
  lastError: null,
}

function getBackendBase(): string {
  const fromEnv = (import.meta as any).env?.VITE_API_BASE_URL as string | undefined
  return getApiBase(fromEnv)
}

async function probeBackend(): Promise<boolean> {
  const ctrl = new AbortController()
  const timeout = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)

  try {
    const res = await fetch(`${getBackendBase()}/sys_check`, { signal: ctrl.signal })
    if (!res.ok) return false
    const json = await res.json().catch(() => null)
    return json?.code === 0
  } catch {
    return false
  } finally {
    clearTimeout(timeout)
  }
}

export const useCheckBackend = (): BackendCheck => {
  const [status, setStatus] = useState<Status>(initialStatus)
  const [tick, setTick] = useState(0)
  const settledRef = useRef(false)

  const retry = useCallback(() => {
    settledRef.current = false
    setStatus(initialStatus)
    setTick(t => t + 1)
  }, [])

  useEffect(() => {
    let cancelled = false
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    let pollTimerId: ReturnType<typeof setTimeout> | null = null
    const tauriUnsubs: Array<() => void> = []

    const markReady = () => {
      if (cancelled || settledRef.current) return
      settledRef.current = true
      setStatus({ loading: false, initialized: true, failed: false, lastError: null })
    }

    const markFailed = (message: string) => {
      if (cancelled || settledRef.current) return
      settledRef.current = true
      setStatus({ loading: false, initialized: false, failed: true, lastError: message })
    }

    const schedulePoll = () => {
      pollTimerId = setTimeout(() => {
        void poll()
      }, POLL_INTERVAL_MS)
    }

    const poll = async () => {
      if (cancelled || settledRef.current) return

      const ok = await probeBackend()
      if (cancelled || settledRef.current) return

      if (ok) {
        markReady()
        return
      }

      setStatus(s => ({
        ...s,
        lastError: 'Backend is not ready yet. Please keep the backend window open.',
      }))
      schedulePoll()
    }

    timeoutId = setTimeout(() => {
      markFailed(
        isTauri
          ? `Backend did not become ready within ${TOTAL_TIMEOUT_MS / 1000}s. Check the backend window and restart the app.`
          : 'Backend is not reachable on port 8483. Start backend/main.py first and keep that window open.',
      )
    }, TOTAL_TIMEOUT_MS)

    if (isTauri) {
      import('@tauri-apps/api/event')
        .then(async ({ listen }) => {
          if (cancelled) return
          const offReady = await listen<number>('backend-ready', () => markReady())
          const offTimeout = await listen<string>('backend-startup-timeout', e => {
            markFailed(typeof e.payload === 'string' ? e.payload : 'Backend startup timed out.')
          })
          const offTerminated = await listen<number | null>('backend-terminated', e => {
            markFailed(`Backend process exited. code=${e.payload ?? 'unknown'}`)
          })
          tauriUnsubs.push(offReady, offTimeout, offTerminated)
        })
        .catch(err => {
          console.warn('[useCheckBackend] Failed to subscribe Tauri events:', err)
        })
    }

    void poll()

    return () => {
      cancelled = true
      if (timeoutId) clearTimeout(timeoutId)
      if (pollTimerId) clearTimeout(pollTimerId)
      tauriUnsubs.forEach(off => {
        try {
          off()
        } catch {
          // noop
        }
      })
    }
  }, [tick])

  return { ...status, retry }
}
