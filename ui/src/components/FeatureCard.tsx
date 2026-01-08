import { CheckCircle2, Circle, Loader2 } from 'lucide-react'
import type { Feature } from '../lib/types'

interface FeatureCardProps {
  feature: Feature
  onClick: () => void
  isInProgress?: boolean
}

// Category color palette names (maps to CSS variables)
const CATEGORY_PALETTES = ['coral', 'blue', 'green', 'amber', 'purple', 'rose', 'teal'] as const

// Generate consistent category palette name based on category string
function getCategoryPalette(category: string): typeof CATEGORY_PALETTES[number] {
  let hash = 0
  for (let i = 0; i < category.length; i++) {
    hash = category.charCodeAt(i) + ((hash << 5) - hash)
  }
  return CATEGORY_PALETTES[Math.abs(hash) % CATEGORY_PALETTES.length]
}

export function FeatureCard({ feature, onClick, isInProgress }: FeatureCardProps) {
  const palette = getCategoryPalette(feature.category)

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left card card-interactive p-4
        ${isInProgress ? 'animate-pulse-soft' : ''}
        ${feature.passes ? 'border-[var(--color-done-border)]' : ''}
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <span
          className="badge text-xs"
          style={{
            backgroundColor: `var(--color-cat-${palette}-bg)`,
            color: `var(--color-cat-${palette}-text)`,
            border: `1px solid var(--color-cat-${palette}-border)`,
          }}
        >
          {feature.category}
        </span>
        <span className="font-mono text-xs text-[var(--color-text-muted)]">
          #{feature.priority}
        </span>
      </div>

      {/* Name */}
      <h3 className="font-display font-medium text-[var(--color-text)] mb-1 line-clamp-2">
        {feature.name}
      </h3>

      {/* Description */}
      <p className="text-sm text-[var(--color-text-secondary)] line-clamp-2 mb-3">
        {feature.description}
      </p>

      {/* Status */}
      <div className="flex items-center gap-2 text-sm">
        {isInProgress ? (
          <>
            <Loader2 size={14} className="animate-spin text-[var(--color-progress)]" />
            <span className="text-[var(--color-progress)] font-medium">Processing...</span>
          </>
        ) : feature.passes ? (
          <>
            <CheckCircle2 size={14} className="text-[var(--color-done)]" />
            <span className="text-[var(--color-done)] font-medium">Complete</span>
          </>
        ) : (
          <>
            <Circle size={14} className="text-[var(--color-text-muted)]" />
            <span className="text-[var(--color-text-muted)]">Pending</span>
          </>
        )}
      </div>
    </button>
  )
}
