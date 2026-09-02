import { motion } from 'framer-motion'
import { ChevronDownIcon, SearchIcon } from './icons.jsx'

export default function SearchBar({
  companyName,
  onCompanyNameChange,
  country,
  onCountryChange,
  countries,
  industryHint,
  onIndustryHintChange,
  onSubmit,
  loading,
}) {
  const canSubmit = companyName.trim() && country && !loading

  function handleSubmit(event) {
    event.preventDefault()
    if (canSubmit) onSubmit()
  }

  return (
    <motion.form
      className="search-panel"
      onSubmit={handleSubmit}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <div className="search-row">
        <div className="search-field">
          <label htmlFor="company-input">
            <span className="required-dot" />
            Company name
          </label>
          <input
            id="company-input"
            type="text"
            placeholder="e.g. Chemstride Industries Pvt Ltd"
            value={companyName}
            onChange={(e) => onCompanyNameChange(e.target.value)}
            autoComplete="off"
            disabled={loading}
            required
          />
        </div>

        <div className="search-field">
          <label htmlFor="country-select">
            <span className="required-dot" />
            Country
          </label>
          <div className="select-wrap">
            <select
              id="country-select"
              value={country}
              onChange={(e) => onCountryChange(e.target.value)}
              disabled={loading}
              required
            >
              <option value="" disabled>
                Select country
              </option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name} ({c.dial_code})
                </option>
              ))}
            </select>
            <ChevronDownIcon />
          </div>
        </div>

        <div className="search-field">
          <label htmlFor="industry-input">Industry hint (optional)</label>
          <input
            id="industry-input"
            type="text"
            placeholder="e.g. specialty chemicals"
            value={industryHint}
            onChange={(e) => onIndustryHintChange(e.target.value)}
            autoComplete="off"
            disabled={loading}
          />
        </div>

        <motion.button
          type="submit"
          className="search-button"
          disabled={!canSubmit}
          whileHover={canSubmit ? { scale: 1.03 } : {}}
          whileTap={canSubmit ? { scale: 0.97 } : {}}
        >
          {loading ? (
            <>
              <span className="spinner" />
              Researching…
            </>
          ) : (
            <>
              <SearchIcon />
              Research Company
            </>
          )}
        </motion.button>
      </div>
    </motion.form>
  )
}
