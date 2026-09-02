import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

const STATUS_MESSAGES = [
  'Searching public sources…',
  'Identifying the official website…',
  'Cross-referencing business portals…',
  'Extracting contact details…',
  'Compiling the dossier…',
]

function SkeletonRow({ wide }) {
  return (
    <div className="skeleton-row">
      <div className="skeleton skeleton-icon" />
      <div className="skeleton-lines">
        <div className={`skeleton skeleton-line${wide ? '' : ' short'}`} />
        <div className="skeleton skeleton-line short" />
      </div>
    </div>
  )
}

export default function Loader({ companyName }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % STATUS_MESSAGES.length)
    }, 1600)
    return () => clearInterval(id)
  }, [])

  return (
    <motion.div
      className="loader-card"
      role="status"
      aria-live="polite"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
    >
      <div className="loader-status">
        <span className="spinner" style={{ borderTopColor: 'var(--accent)', borderColor: 'var(--border-strong)' }} />
        <p className="loader-status-text">
          <AnimatePresence mode="wait">
            <motion.span
              key={step}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
              style={{ display: 'inline-block' }}
            >
              {STATUS_MESSAGES[step]}
            </motion.span>
          </AnimatePresence>{' '}
          <b>{companyName}</b>
        </p>
      </div>
      <div className="loader-body">
        <SkeletonRow wide />
        <SkeletonRow wide />
        <SkeletonRow />
        <SkeletonRow />
      </div>
    </motion.div>
  )
}
