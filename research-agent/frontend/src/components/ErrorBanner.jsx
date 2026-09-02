import { motion } from 'framer-motion'
import { AlertIcon } from './icons.jsx'

export default function ErrorBanner({ message, onRetry }) {
  return (
    <motion.div
      className="error-card"
      role="alert"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
    >
      <div className="error-icon">
        <AlertIcon />
      </div>
      <div>
        <p className="error-title">No record could be compiled</p>
        <p className="error-message">{message}</p>
        {onRetry && (
          <motion.button
            type="button"
            className="error-retry"
            onClick={onRetry}
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
          >
            Try again
          </motion.button>
        )}
      </div>
    </motion.div>
  )
}
