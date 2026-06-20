// components/LazyImage.tsx
import { useInView } from 'react-intersection-observer'
import { FC, useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'

interface LazyImageProps {
  src: string | string[]
  alt?: string
  className?: string
  placeholder?: string
}

const LazyImage: FC<LazyImageProps> = ({ src, alt, className, placeholder = '/placeholder.png' }) => {
  const { ref, inView } = useInView({ triggerOnce: true, threshold: 0.1 })
  const [loaded, setLoaded] = useState(false)
  const [sourceIndex, setSourceIndex] = useState(0)
  const sources = useMemo(() => (Array.isArray(src) ? src : [src]).filter(Boolean), [src])
  const sourceKey = sources.join('\n')
  const currentSource = sources[sourceIndex] || placeholder

  useEffect(() => {
    setLoaded(false)
    setSourceIndex(0)
  }, [sourceKey])

  return (
    <div ref={ref} className={clsx('h-11 w-16 shrink-0 overflow-hidden rounded-md bg-neutral-100', className)}>
      {inView ? (
        <img
          src={currentSource}
          alt={alt}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => {
            setLoaded(false)
            setSourceIndex(index => index + 1)
          }}
          className={clsx(
            'h-full w-full object-cover transition-opacity duration-300',
            loaded ? 'opacity-100' : 'opacity-0',
          )}
        />
      ) : (
        <img src={placeholder} alt="loading" className="h-full w-full object-cover opacity-30" />
      )}
    </div>
  )
}

export default LazyImage
