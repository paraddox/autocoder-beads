import { useState } from 'react'
import { Play, Square, Loader2, Zap } from 'lucide-react'
import {
  useStartAgent,
  useStopAgent,
} from '../hooks/useProjects'
import type { AgentStatus } from '../lib/types'

interface AgentControlProps {
  projectName: string
  status: AgentStatus
  yoloMode?: boolean
}

export function AgentControl({ projectName, status, yoloMode = false }: AgentControlProps) {
  const [yoloEnabled, setYoloEnabled] = useState(false)

  const startAgent = useStartAgent(projectName)
  const stopAgent = useStopAgent(projectName)

  const isLoading =
    startAgent.isPending ||
    stopAgent.isPending

  const handleStart = () => startAgent.mutate(yoloEnabled)
  const handleStop = () => stopAgent.mutate()

  return (
    <div className="flex items-center gap-2">
      {/* Status Indicator */}
      <StatusIndicator status={status} />

      {/* YOLO Mode Indicator */}
      {status === 'running' && yoloMode && (
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[var(--color-pending-bg)] border border-[var(--color-pending-border)] rounded-md">
          <Zap size={12} className="text-[var(--color-pending)]" />
          <span className="font-medium text-xs text-[#9A7B2E]">
            YOLO
          </span>
        </div>
      )}

      {/* Control Buttons */}
      <div className="flex gap-1.5">
        {status === 'not_created' || status === 'stopped' || status === 'crashed' ? (
          <>
            {/* YOLO Toggle */}
            <button
              onClick={() => setYoloEnabled(!yoloEnabled)}
              className={`btn btn-icon ${
                yoloEnabled ? 'btn-warning' : 'btn-secondary'
              }`}
              title="YOLO Mode: Skip testing for rapid prototyping"
            >
              <Zap size={16} />
            </button>
            <button
              onClick={handleStart}
              disabled={isLoading}
              className="btn btn-success btn-icon"
              title={yoloEnabled ? "Start Agent (YOLO Mode)" : "Start Agent"}
            >
              {isLoading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
            </button>
          </>
        ) : status === 'running' ? (
          <button
            onClick={handleStop}
            disabled={isLoading}
            className="btn btn-danger btn-icon"
            title="Stop Agent"
          >
            {isLoading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Square size={16} />
            )}
          </button>
        ) : null}
      </div>
    </div>
  )
}

function StatusIndicator({ status }: { status: AgentStatus }) {
  const statusConfig: Record<AgentStatus, { color: string; label: string; pulse: boolean }> = {
    not_created: {
      color: 'var(--color-text-muted)',
      label: 'Not Created',
      pulse: false,
    },
    stopped: {
      color: 'var(--color-text-muted)',
      label: 'Stopped',
      pulse: false,
    },
    running: {
      color: 'var(--color-done)',
      label: 'Running',
      pulse: true,
    },
    crashed: {
      color: 'var(--color-danger)',
      label: 'Crashed',
      pulse: true,
    },
  }

  const config = statusConfig[status] || statusConfig.stopped

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--color-bg-elevated)] border border-[var(--color-border)] rounded-md">
      <span
        className={`status-dot ${config.pulse ? 'status-dot-pulse' : ''}`}
        style={{ backgroundColor: config.color }}
      />
      <span
        className="font-medium text-sm"
        style={{ color: config.color }}
      >
        {config.label}
      </span>
    </div>
  )
}
