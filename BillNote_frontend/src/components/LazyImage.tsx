// components/LazyImage.tsx
import { useInView } from 'react-intersection-observer'
import { FC, useState } from 'react'
import clsx from 'clsx'

interface LazyImageProps {
  src: string
  alt?: string
  className?: string
  placeholder?: string
}

const LazyImage: FC<LazyImageProps> = ({ src, alt, className, placeholder = '/placeholder.png' }) => {
  const { ref, inView } = useInView({ triggerOnce: true, threshold: 0.1 })
  const [loaded, setLoaded] = useState(false)

  return (
    <div ref={ref} className={clsx('h-11 w-16 shrink-0 overflow-hidden rounded-md bg-neutral-100', className)}>
      {inView ? (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          onLoad={() => setLoaded(true)}
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
