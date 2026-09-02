import { motion } from 'framer-motion'
import {
  GlobeIcon,
  MailIcon,
  PhoneIcon,
  WhatsAppIcon,
  WeChatIcon,
  PersonIcon,
  BadgeIcon,
  MapPinIcon,
  IndustryIcon,
  LanguageIcon,
  ExternalLinkIcon,
  ShieldCheckIcon,
} from './icons.jsx'
import LinkedInSection from './LinkedInSection.jsx'

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.05, delayChildren: 0.05 },
  },
}

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' } },
}

function FieldRow({ icon, label, found, children, badge }) {
  return (
    <motion.div className="field-row" variants={item}>
      <div className="field-icon">{icon}</div>
      <div className="field-body">
        <div className="field-label-row">
          <span className={`status-dot ${found ? 'found' : 'missing'}`} />
          <span className="field-label">{label}</span>
        </div>
        <span className={found ? 'field-value' : 'field-value field-value--empty'}>
          {found ? children : 'Not found'}
        </span>
        {badge}
      </div>
    </motion.div>
  )
}

function websiteHref(website) {
  if (!website) return null
  return /^https?:\/\//i.test(website) ? website : `https://${website}`
}

function whatsappHref(whatsapp) {
  if (!whatsapp) return null
  const digits = whatsapp.replace(/[^\d]/g, '')
  return digits ? `https://wa.me/${digits}` : null
}

function sourceLabel(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function computeConfidence(data) {
  const coreFields = [
    data.website,
    data.email,
    data.phone,
    data.contact_person,
    data.address,
    data.location,
    data.industry,
  ]
  const found = coreFields.filter(Boolean).length
  const ratio = found / coreFields.length
  if (ratio >= 0.7) return { label: 'High confidence', tier: 'high' }
  if (ratio >= 0.35) return { label: 'Medium confidence', tier: 'medium' }
  return { label: 'Low confidence', tier: 'low' }
}

export default function ResultCard({ data }) {
  const {
    company,
    country,
    dial_code: dialCode,
    website,
    email,
    phone,
    whatsapp,
    wechat,
    preferred_messenger: preferredMessenger,
    contact_person: contactPerson,
    designation,
    location,
    address,
    address_original: addressOriginal,
    industry,
    products = [],
    sources = [],
    linkedin,
  } = data

  const site = websiteHref(website)
  const wa = whatsappHref(whatsapp)
  const confidence = computeConfidence(data)
  const hasOriginalAddress = Boolean(addressOriginal)

  return (
    <motion.article
      className="result-card"
      variants={container}
      initial="hidden"
      animate="show"
    >
      <motion.header className="result-header" variants={item}>
        <div className="result-heading-group">
          <p className="result-eyebrow">Company dossier</p>
          <h2 className="result-company">{company || 'Unnamed company'}</h2>
          {country && (
            <p className="result-country">
              {country}
              {dialCode ? ` · ${dialCode}` : ''}
            </p>
          )}
        </div>
        <div className="result-header-right">
          <span className={`confidence-badge ${confidence.tier}`}>
            <ShieldCheckIcon />
            {confidence.label}
          </span>
          {site ? (
            <a className="result-site-link" href={site} target="_blank" rel="noreferrer">
              {website} <ExternalLinkIcon />
            </a>
          ) : (
            <span className="result-site-link result-site-link--empty">Website not found</span>
          )}
        </div>
      </motion.header>

      <div className="result-section">
        <span className="section-label">Contact</span>
        <div className="result-grid">
          <FieldRow icon={<GlobeIcon />} label="Official website" found={!!site}>
            <a href={site} target="_blank" rel="noreferrer">
              {website}
            </a>
          </FieldRow>

          <FieldRow icon={<PhoneIcon />} label="Phone" found={!!phone}>
            <a href={`tel:${phone}`}>{phone}</a>
          </FieldRow>

          <FieldRow icon={<MailIcon />} label="Email" found={!!email}>
            <a href={`mailto:${email}`}>{email}</a>
          </FieldRow>

          <FieldRow icon={<WhatsAppIcon />} label="WhatsApp" found={!!wa}>
            <a href={wa} target="_blank" rel="noreferrer">
              {whatsapp}
            </a>
            {preferredMessenger?.type === 'whatsapp' && (
              <span className="preferred-chip">Preferred</span>
            )}
          </FieldRow>

          <FieldRow icon={<WeChatIcon />} label="WeChat" found={!!wechat}>
            {wechat}
            {preferredMessenger?.type === 'wechat' && (
              <span className="preferred-chip">Preferred</span>
            )}
          </FieldRow>

          <FieldRow icon={<PersonIcon />} label="Contact person" found={!!contactPerson}>
            {contactPerson}
          </FieldRow>

          <FieldRow icon={<BadgeIcon />} label="Designation" found={!!designation}>
            {designation}
          </FieldRow>

          <FieldRow icon={<IndustryIcon />} label="Industry" found={!!industry}>
            {industry}
          </FieldRow>
        </div>
      </div>

      <div className="result-section">
        <span className="section-label">Location &amp; address</span>
        <div className="result-grid" style={{ marginBottom: hasOriginalAddress || address ? 16 : 0 }}>
          <FieldRow icon={<MapPinIcon />} label="Location" found={!!location}>
            {location}
          </FieldRow>
        </div>
        {(address || hasOriginalAddress) && (
          <div className={`address-block${hasOriginalAddress ? ' has-original' : ''}`}>
            <motion.div className="address-pane" variants={item}>
              <span className="address-pane-label">
                <GlobeIcon /> {hasOriginalAddress ? 'English translation' : 'Address'}
              </span>
              <p className="address-pane-text">{address || 'Not found'}</p>
            </motion.div>
            {hasOriginalAddress && (
              <motion.div className="address-pane original" variants={item}>
                <span className="address-pane-label">
                  <LanguageIcon /> Original (Chinese)
                </span>
                <p className="address-pane-text cjk">{addressOriginal}</p>
              </motion.div>
            )}
          </div>
        )}
      </div>

      <div className="result-section">
        <span className="section-label">Products</span>
        {products.length > 0 ? (
          <ul className="product-chips">
            {products.map((product) => (
              <li key={product}>{product}</li>
            ))}
          </ul>
        ) : (
          <p className="field-value field-value--empty">No products identified</p>
        )}
      </div>

      <LinkedInSection data={linkedin} country={country} />

      <div className="result-section">
        <span className="section-label">Sources ({sources.length})</span>
        {sources.length > 0 ? (
          <ol className="source-list">
            {sources.map((url) => (
              <motion.li key={url} variants={item}>
                <a href={url} target="_blank" rel="noreferrer">
                  {sourceLabel(url)} <ExternalLinkIcon />
                </a>
              </motion.li>
            ))}
          </ol>
        ) : (
          <p className="field-value field-value--empty">No sources recorded</p>
        )}
      </div>
    </motion.article>
  )
}
