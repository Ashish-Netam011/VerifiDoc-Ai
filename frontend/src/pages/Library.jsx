import { Container, Card, CardHeader, CardTitle, CardContent } from '@/components/ui'

export function Library() {
  return (
    <Container className="py-12">
      <Card>
        <CardHeader>
          <CardTitle>Document Library</CardTitle>
        </CardHeader>
        <CardContent>
          <p>Document library interface will be implemented here.</p>
        </CardContent>
      </Card>
    </Container>
  )
}