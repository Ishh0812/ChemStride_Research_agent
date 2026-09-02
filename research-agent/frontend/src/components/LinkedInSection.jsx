import { motion } from 'framer-motion'
import { ExternalLinkIcon, LinkedInIcon, PersonIcon } from './icons.jsx'

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' } },
}

function ContactCell({ value, source }) {
  if (!value) return <span className="li-notfound">Not Found</span>
  const href = value.includes('@') ? `mailto:${value}` : `tel:${value}`
  return (
    <span className="li-contact">
      <a href={href}>{value}</a>
      {source && source !== 'LinkedIn' && (
        <span className="li-source-tag">Source: {source}</span>
      )}
    </span>
  )
}

export default function LinkedInSection({ data, country }) {
  if (!data) return null

  const {
    company_page: companyPage,
    role_searched: roleSearched,
    fallback_used: fallbackUsed,
    people = [],
    note,
  } = data

  return (
    <motion.div className="result-section li-section" variants={item}>
      <span className="section-label">
        <LinkedInIcon /> LinkedIn Contacts
      </span>

      <div className="li-meta">
        <div className="li-meta-row">
          <span className="li-meta-label">Company LinkedIn</span>
          {companyPage ? (
            <a className="li-meta-value" href={companyPage} target="_blank" rel="noreferrer">
              {companyPage.replace(/^https?:\/\/(www\.)?/, '')} <ExternalLinkIcon />
            </a>
          ) : (
            <span className="li-meta-value li-notfound">Not Found</span>
          )}
        </div>
        <div className="li-meta-row">
          <span className="li-meta-label">Country</span>
          <span className="li-meta-value">{country}</span>
        </div>
        <div className="li-meta-row">
          <span className="li-meta-label">Role searched</span>
          <span className="li-meta-value">
            {roleSearched || <span className="li-notfound">Not Found</span>}
            {fallbackUsed && <span className="li-fallback-chip">Fallback used</span>}
          </span>
        </div>
      </div>

      {people.length > 0 ? (
        <div className="li-table-wrap">
          <table className="li-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Job Title</th>
                <th>LinkedIn</th>
                <th>Email</th>
                <th>Phone</th>
              </tr>
            </thead>
            <tbody>
              {people.map((person) => (
                <tr key={person.linkedin}>
                  <td className="li-name">
                    {person.name}
                    {/* Employer exactly as LinkedIn stated it, so a
                        similarly-named company is visible at a glance. */}
                    {person.company && (
                      <span className="li-employer">{person.company}</span>
                    )}
                  </td>
                  <td>
                    {person.title || <span className="li-notfound">Not Found</span>}
                    {/* A near-miss title is never presented as the requested role. */}
                    {person.title_match === 'variant' && (
                      <span className="li-variant-chip" title="Related title, not an exact match">
                        related
                      </span>
                    )}
                  </td>
                  <td>
                    <a href={person.linkedin} target="_blank" rel="noreferrer">
                      Profile <ExternalLinkIcon />
                    </a>
                  </td>
                  <td>
                    <ContactCell value={person.email} source={person.contact_source} />
                  </td>
                  <td>
                    <ContactCell value={person.phone} source={person.contact_source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="li-empty">
          <PersonIcon />
          <p>{note || 'Not Found'}</p>
        </div>
      )}
    </motion.div>
  )
}
