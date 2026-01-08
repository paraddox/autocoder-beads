import { FeatureCard } from './FeatureCard'
import type { Feature } from '../lib/types'

interface KanbanColumnProps {
  title: string
  count: number
  features: Feature[]
  color: 'pending' | 'progress' | 'done'
  onFeatureClick: (feature: Feature) => void
}

const colorConfig = {
  pending: {
    dot: 'var(--color-pending)',
    badge: 'badge-pending',
  },
  progress: {
    dot: 'var(--color-progress)',
    badge: 'badge-progress',
  },
  done: {
    dot: 'var(--color-done)',
    badge: 'badge-done',
  },
}

export function KanbanColumn({
  title,
  count,
  features,
  color,
  onFeatureClick,
}: KanbanColumnProps) {
  const config = colorConfig[color]

  return (
    <div className="card overflow-hidden">
      {/* Header */}
      <div className="column-header bg-[var(--color-bg-subtle)]">
        <span
          className="column-dot"
          style={{ backgroundColor: config.dot }}
        />
        <h2 className="font-display text-base font-medium text-[var(--color-text)] flex-1">
          {title}
        </h2>
        <span className={`badge ${config.badge}`}>{count}</span>
      </div>

      {/* Cards */}
      <div className="p-3 space-y-3 max-h-[600px] overflow-y-auto bg-[var(--color-bg)]">
        {features.length === 0 ? (
          <div className="text-center py-8 text-[var(--color-text-muted)] text-sm">
            No features
          </div>
        ) : (
          features.map((feature, index) => (
            <div
              key={feature.id}
              className="animate-slide-in"
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <FeatureCard
                feature={feature}
                onClick={() => onFeatureClick(feature)}
                isInProgress={color === 'progress'}
              />
            </div>
          ))
        )}
      </div>
    </div>
  )
}
