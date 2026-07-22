import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium',
  {
    variants: {
      variant: {
        default: 'border-[var(--accent-edge)] bg-[var(--accent-soft)] text-[var(--accent)]',
        success: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-500',
        warning: 'border-amber-500/20 bg-amber-500/10 text-amber-500',
        danger: 'border-red-500/20 bg-red-500/10 text-red-500',
        secondary: 'border-[var(--border)] bg-[var(--chip-bg)] text-[var(--text-muted)]',
      },
    },
    defaultVariants: { variant: 'default' },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
