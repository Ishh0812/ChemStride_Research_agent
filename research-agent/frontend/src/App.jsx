import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import SearchBar from './components/SearchBar.jsx'
import Loader from './components/Loader.jsx'
import ErrorBanner from './components/ErrorBanner.jsx'
import ResultCard from './components/ResultCard.jsx'
import { researchCompany, getCountries } from './api.js'
import { SunIcon, MoonIcon, SparklesIcon, InboxIcon } from './components/icons.jsx'

function usePreferredTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'system')

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') {
      root.removeAttribute('data-theme')
    } else {
      root.setAttribute('data-theme', theme)
    }
    localStorage.setItem('theme', theme)
  }, [theme])

  const isDark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)

  function toggle() {
    setTheme(isDark ? 'light' : 'dark')
  }

  return { isDark, toggle }
}

export default function App() {
  const { isDark, toggle } = usePreferredTheme()

  const [companyName, setCompanyName] = useState('')
  const [country, setCountry] = useState('')
  const [industryHint, setIndustryHint] = useState('')
  const [countries, setCountries] = useState([])

  const [queriedName, setQueriedName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    getCountries().then(setCountries)
  }, [])

  async function runResearch() {
    const name = companyName.trim()
    if (!name || !country) return

    setLoading(true)
    setError(null)
    setResult(null)
    setQueriedName(name)

    try {
      const data = await researchCompany({ companyName: name, country, industryHint })
      setResult(data)
    } catch (err) {
      setError(err.message || 'Something went wrong while researching this company.')
    } finally {
      setLoading(false)
    }
  }

  let stateKey = 'empty'
  if (loading) stateKey = 'loading'
  else if (error) stateKey = 'error'
  else if (result) stateKey = 'result'

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <SparklesIcon />
          </span>
          <span className="brand-name">Company Intel</span>
          <span className="brand-tag">Beta</span>
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggle}
          aria-label="Toggle dark mode"
        >
          {isDark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>

      <div className="page">
        <header className="page-header">
          <p className="page-eyebrow">
            <SparklesIcon /> AI-powered research
          </p>
          <h1>Look up any company's public footprint</h1>
          <p className="page-subtitle">
            Enter a company name and country to compile its official site, contact
            details, address, and public listings into a single verified dossier.
          </p>
        </header>

        <SearchBar
          companyName={companyName}
          onCompanyNameChange={setCompanyName}
          country={country}
          onCountryChange={setCountry}
          countries={countries}
          industryHint={industryHint}
          onIndustryHintChange={setIndustryHint}
          onSubmit={runResearch}
          loading={loading}
        />

        <section className="results-area">
          {/* Not mode="wait": that holds the incoming card until the outgoing
              one finishes exiting, and a backgrounded tab pauses animation
              frames - so results could sit invisible until the tab is focused. */}
          <AnimatePresence>
            {stateKey === 'loading' && <Loader key="loading" companyName={queriedName} />}
            {stateKey === 'error' && (
              <ErrorBanner key="error" message={error} onRetry={runResearch} />
            )}
            {stateKey === 'result' && <ResultCard key="result" data={result} />}
            {stateKey === 'empty' && (
              <motion.div
                key="empty"
                className="empty-state"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3, ease: 'easeOut' }}
              >
                <span className="empty-state-icon">
                  <InboxIcon />
                </span>
                <p>No company researched yet.</p>
                <p className="empty-state-subtext">
                  Results will appear here as a dossier once a search completes.
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </section>
      </div>
    </div>
  )
}
