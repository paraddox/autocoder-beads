import { CheckCircle2, Circle, Loader2 } from 'lucide-react'
import type { Feature } from '../lib/types'

interface FeatureCardProps {
  feature: Feature
  onClick: () => void
  isInProgress?: boolean
}

// Generate consistent muted color for category
function getCategoryStyle(category: string): { bg: string; text: string; border: string } {
  const palettes = [
    { bg: '#FDF4F2', text: '#B35A43', border: '#F5D4CC' }, // coral
    { bg: '#EEF4FA', text: '#3D6A8F', border: '#B8D4ED' }, // blue
    { bg: '#EEF7F0', text: '#4A7D55', border: '#B4DCC0' }, // green
    { bg: '#FEF9EC', text: '#9A7B2E', border: '#F5DFA0' }, // amber
    { bg: '#F5F3FF', text: '#6B5B95', border: '#D4CCE8' }, // purple
    { bg: '#FFF5F5', text: '#A66060', border: '#F0C8C8' }, // rose
    { bg: '#F0F9FF', text: '#4A7B8A', border: '#B8DCE8' }, // teal
  ]

  let hash = 0
  for (let i = 0; i < category.length; i++) {
    hash = category.charCodeAt(i) + ((hash << 5) - hash)
  }

  return palettes[Math.abs(hash) % palettes.length]
}

export function FeatureCard({ feature, onClick, isInProgress }: FeatureCardProps) {
  const categoryStyle = getCategoryStyle(feature.category)

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
            backgroundColor: categoryStyle.bg,
            color: categoryStyle.text,
            border: `1px solid ${categoryStyle.border}`,
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
